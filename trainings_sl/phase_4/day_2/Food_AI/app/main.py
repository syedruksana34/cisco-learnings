import logging
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from openai import APIError, APIConnectionError, AuthenticationError, RateLimitError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import agent, rag
from .ai_provider import provider
from .database import get_db
from .models import ChatMessage, ChatSession, MenuItem, Order, OrderFeedback, PendingAction, User
from .rate_limit import RateLimiter
from .repository import Repository
from .schemas import ChatRequest, ConfirmRequest, FeedbackRequest, ItemCreate, OrderCreate, SignupRequest, StatusUpdate
from .security import admin_user, basic, current_user, register_user
from .service import FoodService, cancelled_quantity, item_view, order_view, remaining_total

app = FastAPI(title="Savour House", version="1.0")
log = logging.getLogger("food_ai")
limiter = RateLimiter()
static = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static), name="static")


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    address = request.client.host if request.client else "unknown"
    sensitive = request.method == "POST" and (request.url.path.endswith("/messages") or request.url.path == "/api/documents")
    if request.method == "POST" and request.url.path == "/api/auth/signup":
        bucket, limit = "signup", 10
    else:
        bucket, limit = ("ai", 20) if sensitive else ("general", 120)
    if not limiter.allow(address, bucket, limit):
        response = error(request, "RATE_LIMITED", "Too many requests; try again later", 429, {"Retry-After": "60"})
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def error(request, code, message, status, headers=None):
    return JSONResponse(status_code=status, content={"code": code, "message": message,
                        "request_id": request.state.request_id}, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return error(request, f"HTTP_{exc.status_code}", str(exc.detail), exc.status_code, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    messages = [f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()]
    return error(request, "VALIDATION_ERROR", "; ".join(messages), 422)


@app.exception_handler(RateLimitError)
async def rate_limit_error(request, exc):
    body = exc.body if isinstance(exc.body, dict) else {}
    details = body.get("error", body)
    if isinstance(details, dict) and (details.get("type") == "insufficient_quota"
                                     or details.get("code") in ("insufficient_quota", "credit_balance_exhausted")):
        return error(request, "AI_QUOTA_EXHAUSTED",
                     "AI credits or quota are exhausted. Check your provider's billing and usage.", 429)
    return error(request, "AI_RATE_LIMIT", "AI provider rate limit reached. Check your quota or try again later.", 429)


@app.exception_handler(AuthenticationError)
async def ai_auth_error(request, exc):
    return error(request, "AI_AUTHENTICATION_ERROR", "AI provider rejected the API key. Check your configuration.", 503)


@app.exception_handler(APIError)
@app.exception_handler(APIConnectionError)
async def ai_error(request, exc):
    log.warning("AI provider unavailable: %s", type(exc).__name__)
    message = ("Local Ollama is unavailable or the model is missing. Check the Ollama service and installed models."
               if provider() == "ollama" else "AI provider is unavailable")
    return error(request, "AI_UNAVAILABLE", message, 503)


@app.exception_handler(OperationalError)
async def database_error(request, exc):
    code = exc.orig.args[0] if exc.orig and exc.orig.args else None
    log.warning("Database operation failed: %s", code)
    message = ("MySQL rejected the database credentials. Check DATABASE_URL in .env."
               if code == 1045 else "Database is unavailable. Check the server and database configuration.")
    return error(request, "DATABASE_UNAVAILABLE", message, 503)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    log.exception("Unexpected error request_id=%s", request.state.request_id)
    return error(request, "INTERNAL_ERROR", "An unexpected error occurred", 500)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(static / "index.html")


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


@app.post("/api/auth/signup", status_code=201)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    user = register_user(db, data)
    return {"id": user.id, "username": user.username, "role": user.role}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@app.get("/api/menu_items")
def menu_items(category: str | None = None, vegetarian: bool | None = None,
               max_price: float | None = Query(None, gt=0), keyword: str | None = Query(None, max_length=120),
               db: Session = Depends(get_db)):
    query = select(MenuItem).where(MenuItem.active.is_(True))
    if category:
        query = query.where(MenuItem.category == category)
    if vegetarian is not None:
        query = query.where(MenuItem.vegetarian == vegetarian)
    if max_price is not None:
        query = query.where(MenuItem.price <= max_price)
    if keyword:
        query = query.where(MenuItem.title.contains(keyword, autoescape=True))
    return [item_view(item) for item in db.scalars(query.order_by(MenuItem.id)).all()]


@app.get("/api/menu_items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    return item_view(FoodService(db).menu_item(item_id))


@app.post("/api/menu_items", status_code=201)
def create_item(data: ItemCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = FoodService(db).create_item(data)
    db.commit()
    return item_view(item)


@app.put("/api/menu_items/{item_id}")
def update_item(item_id: int, data: ItemCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = FoodService(db).update_item(item_id, data)
    db.commit()
    return item_view(item)


@app.delete("/api/menu_items/{item_id}", status_code=204)
def delete_item(item_id: int, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    FoodService(db).disable_item(item_id)
    db.commit()


@app.post("/api/orders", status_code=201)
def create_order(data: OrderCreate, idempotency_key: str = Header(min_length=1, max_length=128),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = FoodService(db).create_order(data, user, idempotency_key)
    db.commit()
    return order_view(order)


@app.get("/api/orders")
def orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    orders = db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())).all()
    item_ids = {line.item_id for order in orders for line in order.lines}
    items = {item.id: item for item in db.scalars(select(MenuItem).where(MenuItem.id.in_(item_ids))).all()} if item_ids else {}
    order_ids = [order.id for order in orders]
    feedback = {entry.order_id: entry for entry in db.scalars(
        select(OrderFeedback).where(OrderFeedback.order_id.in_(order_ids))).all()} if order_ids else {}
    result = []
    for order in orders:
        view = order_view(order)
        entry = feedback.get(order.id)
        view["feedback"] = feedback_view(entry) if entry else None
        view["remaining_total"] = str(remaining_total(order))
        for line, stored_line in zip(view["lines"], order.lines):
            item = items[line["item_id"]]
            line["title"] = item.title
            line["category"] = item.category
            line["cancelled_quantity"] = cancelled_quantity(stored_line)
        result.append(view)
    return result


def feedback_view(feedback: OrderFeedback):
    return {"order_id": feedback.order_id, "rating": feedback.rating, "comment": feedback.comment,
            "updated_at": feedback.updated_at.isoformat()}


@app.put("/api/orders/{order_id}/feedback")
def save_feedback(order_id: int, data: FeedbackRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if not order:
        raise HTTPException(404, "Order not found")
    feedback = db.scalar(select(OrderFeedback).where(OrderFeedback.order_id == order.id))
    if feedback is None:
        feedback = OrderFeedback(order_id=order.id, rating=data.rating, comment=data.comment.strip())
        db.add(feedback)
    else:
        feedback.rating = data.rating
        feedback.comment = data.comment.strip()
    db.commit()
    return feedback_view(feedback)


@app.get("/api/admin/feedback")
def admin_feedback(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                   user: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.execute(select(OrderFeedback, User.username).join(Order, Order.id == OrderFeedback.order_id)
                      .join(User, User.id == Order.user_id)
                      .order_by(OrderFeedback.updated_at.desc(), OrderFeedback.id.desc())
                      .offset(offset).limit(limit)).all()
    return [{**feedback_view(feedback), "username": username} for feedback, username in rows]


@app.get("/api/orders/{order_id}")
def get_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return order_view(FoodService(db).get_order(order_id, user))


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = FoodService(db).cancel_order(order_id, user)
    db.commit()
    return order_view(order)


@app.patch("/api/admin/orders/{order_id}/status")
def change_status(order_id: int, data: StatusUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    order = FoodService(db).change_status(order_id, data.status)
    db.commit()
    return order_view(order)


@app.post("/api/documents", status_code=201)
def upload_document(file: UploadFile = File(...), user: User = Depends(admin_user), db: Session = Depends(get_db)):
    raw = file.file.read(rag.MAX_UPLOAD + 1)
    doc = rag.index_document(db, user, file.filename or "", raw)
    db.commit()
    return {"id": doc.id, "filename": doc.filename, "version": doc.version, "status": doc.status}


@app.post("/api/chat/sessions", status_code=201)
def create_session(user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = ChatSession(user_id=user.id)
    db.add(session)
    db.commit()
    return {"id": session.id, "title": session.title}


@app.get("/api/chat/sessions")
def sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": s.id, "title": s.title} for s in db.scalars(select(ChatSession)
            .where(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc())).all()]


@app.get("/api/chat/sessions/{session_id}/messages")
def history(session_id: int, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not Repository(db).chat(session_id, user.id):
        raise HTTPException(404, "Chat session not found")
    messages = db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.seq_no > after)
                          .order_by(ChatMessage.seq_no).limit(limit)).all()
    action_ids = [m.details["action_id"] for m in messages if m.role == "assistant"
                  and m.content.startswith(("Action confirmed: {", "Action rejected: {"))
                  and isinstance(m.details.get("action_id"), int)]
    previous_actions = {a.id: a for a in db.scalars(select(PendingAction).where(
        PendingAction.id.in_(action_ids), PendingAction.session_id == session_id,
        PendingAction.user_id == user.id)).all()} if action_ids else {}
    return [{"seq_no": m.seq_no, "role": m.role,
             "content": agent.action_summary(previous_actions[m.details["action_id"]])
             if m.role == "assistant" and isinstance(m.details.get("action_id"), int)
             and m.content.startswith(("Action confirmed: {", "Action rejected: {"))
             and m.details.get("action_id") in previous_actions else m.content, "details": m.details,
             "created_at": m.created_at.isoformat()} for m in messages]


@app.get("/api/chat/sessions/{session_id}/actions")
def actions(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not Repository(db).chat(session_id, user.id):
        raise HTTPException(404, "Chat session not found")
    actions = db.scalars(select(PendingAction).where(PendingAction.session_id == session_id,
                         PendingAction.user_id == user.id, PendingAction.status == "PENDING")).all()
    item_ids = {line["item_id"] for action in actions if action.action == "cancel_order"
                for line in action.preview["lines"]}
    titles = dict(db.execute(select(MenuItem.id, MenuItem.title).where(MenuItem.id.in_(item_ids))).all()) if item_ids else {}
    result = []
    for action in actions:
        preview = action.preview
        if action.action == "cancel_order":
            preview = {**preview, "lines": [{**line, "title": titles[line["item_id"]]}
                                            for line in preview["lines"]]}
        result.append({"id": action.id, "action": action.action, "preview": preview,
                       "expires_at": action.expires_at.isoformat()})
    return result


@app.post("/api/chat/sessions/{session_id}/messages")
def post_message(session_id: int, data: ChatRequest, user: User = Depends(current_user),
                 credentials: HTTPBasicCredentials = Depends(basic), db: Session = Depends(get_db)):
    return agent.chat(db, session_id, user, (credentials.username, credentials.password), data.message)


@app.post("/api/chat/actions/{action_id}/confirm")
def confirm(action_id: int, data: ConfirmRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return agent.confirm_action(db, user, action_id, data.confirm)
