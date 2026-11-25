import hashlib
import json
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import ItemCancellation, MenuItem, Order, OrderFeedback, OrderLine, User
from .repository import Repository
from .schemas import ItemCreate, OrderCreate


def order_view(order: Order):
    return {
        "id": order.id, "status": order.status, "total": str(order.total),
        "created_at": order.created_at.isoformat(),
        "lines": [{"item_id": line.item_id, "quantity": line.quantity, "unit_price": str(line.unit_price)} for line in order.lines],
    }


def item_view(item: MenuItem):
    return {"id": item.id, "title": item.title, "category": item.category, "vegetarian": item.vegetarian,
            "price": str(item.price), "capacity": item.capacity, "active": item.active}


def cancelled_quantity(line: OrderLine):
    return sum(cancellation.quantity for cancellation in line.cancellations)


def remaining_total(order: Order):
    if order.status == "CANCELLED":
        return Decimal("0")
    return sum((line.unit_price * (line.quantity - cancelled_quantity(line)) for line in order.lines), Decimal("0"))


def highly_rated_items(db: Session, category: str | None = None, vegetarian: bool | None = None):
    single_item_orders = (select(OrderLine.order_id).group_by(OrderLine.order_id)
                          .having(func.count(OrderLine.id) == 1))
    cancelled_lines = select(ItemCancellation.order_line_id)
    average = func.avg(OrderFeedback.rating)
    query = (select(MenuItem.id, MenuItem.title, MenuItem.category, MenuItem.price,
                    average.label("average"), func.count(OrderFeedback.id).label("rating_count"))
             .join(OrderLine, OrderLine.item_id == MenuItem.id)
             .join(Order, Order.id == OrderLine.order_id)
             .join(OrderFeedback, OrderFeedback.order_id == Order.id)
             .where(MenuItem.active.is_(True), Order.status != "CANCELLED",
                    Order.id.in_(single_item_orders), OrderLine.id.not_in(cancelled_lines)))
    if category:
        query = query.where(MenuItem.category == category)
    if vegetarian is not None:
        query = query.where(MenuItem.vegetarian.is_(vegetarian))
    query = (query.group_by(MenuItem.id, MenuItem.title, MenuItem.category, MenuItem.price)
             .having(average >= 4)
             .order_by(average.desc(), func.count(OrderFeedback.id).desc(), MenuItem.title.asc())
             .limit(10))
    return [{"id": row.id, "title": row.title, "category": row.category, "price": str(row.price),
             "average": f"{Decimal(str(row.average)):.2f}", "rating_count": row.rating_count}
            for row in db.execute(query)]


class FoodService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = Repository(db)

    def menu_item(self, item_id: int, *, include_inactive: bool = False, lock: bool = False):
        item = self.repo.item(item_id, lock)
        if not item or (not item.active and not include_inactive):
            raise HTTPException(404, "Menu item not found")
        return item

    def create_item(self, data: ItemCreate):
        item = MenuItem(**data.model_dump())
        self.db.add(item)
        self.db.flush()
        return item

    def update_item(self, item_id: int, data: ItemCreate):
        item = self.menu_item(item_id, include_inactive=True, lock=True)
        for key, value in data.model_dump().items():
            setattr(item, key, value)
        self.db.flush()
        return item

    def disable_item(self, item_id: int):
        item = self.menu_item(item_id, include_inactive=True, lock=True)
        item.active = False
        self.db.flush()

    def get_order(self, order_id: int, user: User, lock: bool = False):
        order = self.repo.order(order_id, lock)
        if not order or (order.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "Order not found")
        return order

    def preview_order(self, data: OrderCreate, lock: bool = False):
        result = []
        for line in sorted(data.lines, key=lambda x: x.item_id):
            item = self.menu_item(line.item_id, lock=lock)
            if item.capacity < line.quantity:
                raise HTTPException(409, f"Insufficient portions for {item.title}")
            result.append({"item_id": item.id, "title": item.title, "quantity": line.quantity,
                           "unit_price": str(item.price)})
        return result

    def create_order(self, data: OrderCreate, user: User, key: str, expected: list | None = None):
        request_hash = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
        self.db.execute(select(User.id).where(User.id == user.id).with_for_update())
        existing = self.db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == key)
                                  .with_for_update())
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, "Idempotency key was already used for a different order")
            return existing
        preview = self.preview_order(data, lock=True)
        if expected is not None and preview != expected:
            raise HTTPException(409, "Order terms changed; request a new confirmation")
        total = sum((Decimal(row["unit_price"]) * row["quantity"] for row in preview), Decimal("0"))
        order = Order(user_id=user.id, total=total, idempotency_key=key, request_hash=request_hash)
        self.db.add(order)
        for row in preview:
            item = self.repo.item(row["item_id"])
            item.capacity -= row["quantity"]
            order.lines.append(OrderLine(item_id=item.id, quantity=row["quantity"], unit_price=Decimal(row["unit_price"])))
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == key))
            if existing and existing.request_hash == request_hash:
                return existing
            raise HTTPException(409, "Order conflicts with an existing request")
        return order

    def cancel_order(self, order_id: int, user: User):
        order = self.get_order(order_id, user, lock=True)
        if order.user_id != user.id:
            raise HTTPException(404, "Order not found")
        if order.status == "CANCELLED":
            return order
        if order.status != "CONFIRMED":
            raise HTTPException(409, "Order can only be cancelled before preparation")
        for line in sorted(order.lines, key=lambda x: x.item_id):
            self.repo.item(line.item_id, lock=True).capacity += line.quantity - cancelled_quantity(line)
        order.status = "CANCELLED"
        self.db.flush()
        return order

    def cancel_item(self, order_id: int, item_id: int, quantity: int, user: User, expected: dict):
        order = self.get_order(order_id, user, lock=True)
        if order.user_id != user.id:
            raise HTTPException(404, "Order not found")
        if order.status != "CONFIRMED":
            raise HTTPException(409, "Items can only be cancelled before preparation")
        line = next((line for line in order.lines if line.item_id == item_id), None)
        if not line:
            raise HTTPException(404, "Item not found in order")
        remaining = line.quantity - cancelled_quantity(line)
        if order_view(order) != expected["order"] or remaining != expected["remaining_quantity"]:
            raise HTTPException(409, "Order changed; request a new confirmation")
        if quantity < 1 or quantity > remaining:
            raise HTTPException(409, "Requested quantity is no longer available to cancel")
        item = self.repo.item(item_id, lock=True)
        line.cancellations.append(ItemCancellation(quantity=quantity))
        item.capacity += quantity
        if all(line.quantity == cancelled_quantity(line) for line in order.lines):
            order.status = "CANCELLED"
        self.db.flush()
        return {"order_id": order.id, "item_id": item_id, "title": item.title, "quantity": quantity,
                "status": order.status, "remaining_total": str(remaining_total(order))}

    def change_status(self, order_id: int, status: str):
        order = self.repo.order(order_id, lock=True)
        if not order:
            raise HTTPException(404, "Order not found")
        allowed = {"CONFIRMED": "PREPARING", "PREPARING": "READY", "READY": "DELIVERED"}
        if allowed.get(order.status) != status:
            raise HTTPException(409, "Invalid status transition")
        order.status = status
        self.db.flush()
        return order
