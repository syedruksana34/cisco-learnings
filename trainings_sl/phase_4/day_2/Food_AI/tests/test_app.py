import os
import tempfile
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

test_dir = tempfile.TemporaryDirectory(prefix="food-ai-tests-")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{test_dir.name}/test.sqlite")

from app import agent, ai_provider, rag
from app.database import Base, SessionLocal, engine
from app.main import app, limiter
from app.models import ChatMessage, MenuItem, User
from app.rate_limit import RateLimiter
from app.seed import BASE_ITEMS, EXTRA_ITEMS, ITEMS, add_extra_items
from app.security import hasher


@pytest.fixture(autouse=True)
def database():
    limiter.requests.clear()
    if engine.dialect.name == "mysql" and engine.url.database != "food_ai_test":
        raise RuntimeError("MySQL tests require a dedicated database named food_ai_test")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        db.add_all([
            User(username="alice", password_hash=hasher.hash("alice-password"), role="user"),
            User(username="bob", password_hash=hasher.hash("bob-password"), role="user"),
            User(username="admin", password_hash=hasher.hash("admin-password"), role="admin"),
            MenuItem(title="Masala Dosa", category="Breakfast", vegetarian=True, price="90.00", capacity=2),
        ])
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


ALICE = ("alice", "alice-password")
BOB = ("bob", "bob-password")
ADMIN = ("admin", "admin-password")
LINE = {"lines": [{"item_id": 1, "quantity": 1}]}


def order(client, key="key-1", auth=ALICE, data=LINE):
    return client.post("/api/orders", json=data, headers={"Idempotency-Key": key}, auth=auth)


def test_signup_and_signin(client):
    signup = client.post("/api/auth/signup", json={"username": "new.user", "password": "secure-password"})
    assert signup.status_code == 201
    assert signup.json()["role"] == "user"
    assert "password" not in signup.json()
    assert client.get("/api/auth/me", auth=("new.user", "secure-password")).json()["username"] == "new.user"
    assert client.get("/api/auth/me", auth=("new.user", "wrong-password")).status_code == 401
    assert client.post("/api/auth/signup", json={"username": "new.user", "password": "secure-password"}).status_code == 409
    assert client.post("/api/auth/signup", json={"username": "new-admin", "password": "secure-password",
                                                  "role": "admin"}).status_code == 422
    item = {"title": "Tomato Soup", "category": "Starter", "vegetarian": True, "price": "80.00", "capacity": 10}
    assert client.post("/api/menu_items", auth=("new.user", "secure-password"), json=item).status_code == 403
    assert client.post("/api/auth/signup", json={"username": "bad:name", "password": "secure-password"}).status_code == 422
    response = client.post("/api/auth/signup", json={"username": "another", "password": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text


def test_menu_crud_and_authorization(client):
    item = {"title": "Paneer Biryani", "category": "Main", "vegetarian": True, "price": "180.00", "capacity": 10}
    assert client.post("/api/menu_items", json=item, auth=ALICE).status_code == 403
    created = client.post("/api/menu_items", json=item, auth=ADMIN)
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert len(client.get("/api/menu_items", params={"vegetarian": True, "max_price": 100}).json()) == 1
    item["price"] = "190.00"
    assert client.put(f"/api/menu_items/{item_id}", json=item, auth=ADMIN).json()["price"] == "190.00"
    assert client.delete(f"/api/menu_items/{item_id}", auth=ADMIN).status_code == 204
    assert client.get(f"/api/menu_items/{item_id}").status_code == 404
    item["price"] = "-1"
    assert client.post("/api/menu_items", json=item, auth=ADMIN).status_code == 422
    assert client.get("/api/orders").status_code == 401


def test_order_idempotency_ownership_and_cancel(client):
    created = order(client)
    assert created.status_code == 201
    assert created.json()["total"] == "90.00"
    assert order(client).json()["id"] == created.json()["id"]
    assert order(client, data={"lines": [{"item_id": 1, "quantity": 2}]}).status_code == 409
    assert client.get("/api/menu_items/1").json()["capacity"] == 1
    assert client.get("/api/orders/1", auth=BOB).status_code == 404
    assert client.post("/api/orders/1/cancel", auth=BOB).status_code == 404
    assert client.post("/api/orders/1/cancel", auth=ALICE).json()["status"] == "CANCELLED"
    assert client.post("/api/orders/1/cancel", auth=ALICE).json()["status"] == "CANCELLED"
    assert client.get("/api/menu_items/1").json()["capacity"] == 2
    assert order(client, "bad", data={"lines": [{"item_id": 1, "quantity": 3}]}).status_code == 409
    assert order(client, "invalid", data={"lines": [{"item_id": 1, "quantity": 0}]}).status_code == 422


def test_order_status_transition(client):
    order(client)
    assert client.patch("/api/admin/orders/1/status", auth=ALICE, json={"status": "PREPARING"}).status_code == 403
    assert client.patch("/api/admin/orders/1/status", auth=ADMIN, json={"status": "READY"}).status_code == 409
    assert client.patch("/api/admin/orders/1/status", auth=ADMIN, json={"status": "PREPARING"}).status_code == 200
    assert client.post("/api/orders/1/cancel", auth=ALICE).status_code == 409


def test_order_feedback_create_update_privacy_and_validation(client, monkeypatch):
    assert order(client).status_code == 201
    assert order(client, "bob", auth=BOB).status_code == 201
    path = "/api/orders/1/feedback"
    assert client.put(path, json={"rating": 5}).status_code == 401
    assert client.put(path, auth=BOB, json={"rating": 5}).status_code == 404
    assert client.put(path, auth=ADMIN, json={"rating": 5}).status_code == 404
    for data in ({"rating": 0}, {"rating": 6}, {"rating": 1.5}, {"rating": True},
                 {"rating": 5, "comment": "x" * 1001}, {"rating": 5, "user_id": 2}):
        assert client.put(path, auth=ALICE, json=data).status_code == 422
    created = client.put(path, auth=ALICE, json={"rating": 4, "comment": " Great food! "})
    assert created.status_code == 200 and created.json()["comment"] == "Great food!"
    assert client.get("/api/orders", auth=ALICE).json()[0]["feedback"]["rating"] == 4
    assert client.get("/api/orders", auth=BOB).json()[0]["feedback"] is None
    assert client.get("/api/admin/feedback", auth=ALICE).status_code == 403
    assert client.get("/api/admin/feedback").status_code == 401
    updated = client.put(path, auth=ALICE, json={"rating": 5, "comment": "<script>alert(1)</script>"})
    assert updated.json()["rating"] == 5
    entries = client.get("/api/admin/feedback", auth=ADMIN).json()
    assert len(entries) == 1 and entries[0]["username"] == "alice"
    assert entries[0]["comment"] == "<script>alert(1)</script>"
    monkeypatch.setattr(agent, "api_get", lambda path, auth, params=None: client.get(path, auth=auth).json())
    assert "feedback" not in agent.run_tool(None, 1, None, ALICE, "list_orders", {})["orders"][0]
    assert client.post("/api/orders/1/cancel", auth=ALICE).status_code == 200
    assert client.put(path, auth=ALICE, json={"rating": 3}).json()["comment"] == ""


def test_high_rated_food_aggregates_single_dish_orders(client, monkeypatch):
    with SessionLocal.begin() as db:
        db.get(MenuItem, 1).capacity = 20
        db.add_all([
            MenuItem(title="Soup", category="Starter", vegetarian=True, price="80.00", capacity=20),
            MenuItem(title="Chicken", category="Main", vegetarian=False, price="120.00", capacity=20),
        ])
    def rate(key, lines, rating, auth=ALICE):
        created = order(client, key, auth, {"lines": lines}).json()
        assert client.put(f"/api/orders/{created['id']}/feedback", auth=auth,
                          json={"rating": rating, "comment": "private text"}).status_code == 200
        return created["id"]
    dosa = [{"item_id": 1, "quantity": 1}]
    soup = [{"item_id": 2, "quantity": 1}]
    chicken = [{"item_id": 3, "quantity": 1}]
    rate("dosa1", dosa, 5)
    rate("dosa2", dosa, 3, BOB)
    rate("soup1", soup, 5)
    rate("chicken1", chicken, 3)
    rate("multi", dosa + chicken, 5)
    cancelled = rate("cancelled", chicken, 5)
    assert client.post(f"/api/orders/{cancelled}/cancel", auth=ALICE).status_code == 200
    with SessionLocal() as db:
        rows = agent.highly_rated_items(db)
        assert [(row["title"], row["average"], row["rating_count"]) for row in rows] == [
            ("Soup", "5.00", 1), ("Masala Dosa", "4.00", 2)]
        assert [row["title"] for row in agent.highly_rated_items(db, category="Breakfast", vegetarian=True)] == ["Masala Dosa"]
        assert agent.highly_rated_items(db, vegetarian=False) == []
    monkeypatch.setattr(agent, "client", lambda: pytest.fail("AI should not be called"))
    sid = client.post("/api/chat/sessions", auth=BOB).json()["id"]
    for text in ("High rated food", "show me top rated dishes", "highest rated"):
        result = client.post(f"/api/chat/sessions/{sid}/messages", auth=BOB, json={"message": text})
        assert result.status_code == 200
        message = result.json()["message"]
        assert "Soup (Starter): 5.00/5 from 1 rating" in message
        assert "Masala Dosa (Breakfast): 4.00/5 from 2 ratings" in message
        assert "Chicken" not in message and "private text" not in message and "alice" not in message
        assert "These are based on ratings" not in message and "One rating is enough" not in message
    assert client.put("/api/orders/1/feedback", auth=ALICE, json={"rating": 1}).status_code == 200
    with SessionLocal.begin() as db:
        db.query(MenuItem).filter_by(title="Soup").one().active = False
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=BOB, json={"message": "High rated food"}).json()
    assert "No matching active dishes" in result["message"]
    assert "These are based on ratings" not in result["message"]


def test_filtered_high_rated_food_tool_and_unverified_response(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    assert order(client).status_code == 201
    assert client.put("/api/orders/1/feedback", auth=ALICE, json={"rating": 5}).status_code == 200
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    response = ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [
        {"id": "tool-1", "type": "function", "function": {
            "name": "highly_rated_food", "arguments": '{"category":"Breakfast","vegetarian":true}'}}]})
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: response)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    message = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                          json={"message": "show highly rated vegetarian Breakfast dishes"}).json()["message"]
    assert "Filters: category: Breakfast, vegetarian" in message and "Masala Dosa" in message
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: ChatCompletionMessage(
        role="assistant", content="The soup is rated 5 stars."))
    message = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                          json={"message": "show highest rated vegetarian food"}).json()["message"]
    assert "couldn't retrieve" in message and "soup" not in message


def test_high_rated_food_excludes_partial_cancellation(client):
    assert order(client, data={"lines": [{"item_id": 1, "quantity": 2}]}).status_code == 201
    assert client.put("/api/orders/1/feedback", auth=ALICE, json={"rating": 5}).status_code == 200
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                           json={"message": "cancel one masala dosa order 1"}).json()
    assert client.post(f"/api/chat/actions/{response['pending_action_id']}/confirm",
                       auth=ALICE, json={"confirm": True}).status_code == 200
    with SessionLocal() as db:
        assert agent.highly_rated_items(db) == []


def test_order_list_includes_names_for_all_items_including_disabled(client):
    with SessionLocal.begin() as db:
        db.add(MenuItem(title="Soup", category="Starter", vegetarian=True, price="80.00", capacity=4))
    data = {"lines": [{"item_id": 1, "quantity": 2}, {"item_id": 2, "quantity": 1}]}
    assert order(client, data=data).status_code == 201
    with SessionLocal.begin() as db:
        db.get(MenuItem, 2).title = "Tomato Soup"
        db.get(MenuItem, 2).active = False
        db.get(MenuItem, 2).price = "100.00"
    orders = client.get("/api/orders", auth=ALICE).json()
    assert len(orders) == 1
    assert orders[0]["total"] == "260.00"
    assert orders[0]["lines"] == [
        {"item_id": 1, "title": "Masala Dosa", "category": "Breakfast", "quantity": 2, "unit_price": "90.00", "cancelled_quantity": 0},
        {"item_id": 2, "title": "Tomato Soup", "category": "Starter", "quantity": 1, "unit_price": "80.00", "cancelled_quantity": 0},
    ]
    assert client.get("/api/orders", auth=BOB).json() == []
    assert client.post("/api/orders/1/cancel", auth=ALICE).json()["status"] == "CANCELLED"
    assert client.get("/api/orders", auth=ALICE).json()[0]["lines"] == orders[0]["lines"]


def test_pending_action_confirm_once_and_reject(client):
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        action = agent.prepare(db, sid, user, "create_order", LINE)
    action_id = action["pending_action_id"]
    assert client.get("/api/orders", auth=ALICE).json() == []
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=BOB, json={"confirm": True}).status_code == 404
    first = client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True})
    assert first.json()["status"] == "CONFIRMED"
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json() == first.json()
    assert len(client.get("/api/orders", auth=ALICE).json()) == 1
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        action2 = agent.prepare(db, sid, user, "cancel_order", {"order_id": first.json()["outcome"]["id"]})
    assert client.post(f"/api/chat/actions/{action2['pending_action_id']}/confirm", auth=ALICE,
                       json={"confirm": False}).json()["status"] == "REJECTED"
    assert client.get("/api/orders/1", auth=ALICE).json()["status"] == "CONFIRMED"
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=BOB).status_code == 404
    messages = client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()
    assert len(messages) == 2
    summary = messages[0]["content"]
    for text in ("Your order has been placed.", "Order #1", "Status: Confirmed",
                 "Total: INR 90.00", "Masala Dosa: 1 × INR 90.00"):
        assert text in summary
    assert "{" not in summary
    assert messages[1]["content"] == "Action rejected. No changes were made."


def test_legacy_confirmation_history_is_scoped_and_readable(client):
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    other_sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        action_id = agent.prepare(db, sid, user, "create_order", LINE)["pending_action_id"]
    result = client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json()
    legacy = 'Action confirmed: {"id": 1}'
    with SessionLocal.begin() as db:
        message = db.query(ChatMessage).filter_by(session_id=sid).one()
        message.content = legacy
        agent.append_message(db, sid, user.id, "user", legacy, {"action_id": action_id})
        agent.append_message(db, other_sid, user.id, "assistant", legacy, {"action_id": action_id})
    assert result["outcome"]["id"] == 1
    messages = client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()
    assert "Masala Dosa: 1 × INR 90.00" in messages[0]["content"]
    assert messages[1]["content"] == legacy
    assert client.get(f"/api/chat/sessions/{other_sid}/messages", auth=ALICE).json()[0]["content"] == legacy
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=BOB).status_code == 404
    with SessionLocal() as db:
        assert db.query(ChatMessage).filter_by(session_id=sid, seq_no=1).one().content == legacy


def test_confirmation_rechecks_price(client):
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        pending = agent.prepare(db, sid, user, "create_order", LINE)
        db.get(MenuItem, 1).price = "100.00"
    response = client.post(f"/api/chat/actions/{pending['pending_action_id']}/confirm",
                           auth=ALICE, json={"confirm": True})
    assert response.status_code == 409
    assert client.get("/api/orders", auth=ALICE).json() == []


def test_admin_agent_catalog_crud_and_order_status(client):
    sid = client.post("/api/chat/sessions", auth=ADMIN).json()["id"]
    item = {"title": "Tomato Soup", "category": "Starter", "vegetarian": True,
            "price": "80.00", "capacity": 10, "active": True}
    def prepare(name, args):
        with SessionLocal.begin() as db:
            user = db.query(User).filter_by(username="admin").one()
            return agent.prepare(db, sid, user, name, args)["pending_action_id"]
    def confirm(action_id):
        return client.post(f"/api/chat/actions/{action_id}/confirm", auth=ADMIN, json={"confirm": True})
    action_id = prepare("create_menu_item", {"item": item})
    created = confirm(action_id).json()["outcome"]
    assert created["title"] == "Tomato Soup"
    item["price"] = "95.00"
    action_id = prepare("update_menu_item", {"item_id": created["id"], "item": item})
    assert confirm(action_id).json()["outcome"]["price"] == "95.00"
    action_id = prepare("delete_menu_item", {"item_id": created["id"]})
    assert confirm(action_id).json()["status"] == "CONFIRMED"
    assert client.get(f"/api/menu_items/{created['id']}").status_code == 404
    order(client)
    action_id = prepare("update_order_status", {"order_id": 1, "status": "PREPARING"})
    assert confirm(action_id).json()["outcome"]["status"] == "PREPARING"
    messages = client.get(f"/api/chat/sessions/{sid}/messages", auth=ADMIN).json()
    assert "Menu item created: Tomato Soup" in messages[0]["content"]
    assert "Menu item updated: Tomato Soup" in messages[1]["content"]
    assert "Price: INR 95.00" in messages[1]["content"]
    assert "Menu item disabled: Tomato Soup" in messages[2]["content"]
    assert "Order #1" in messages[3]["content"] and "Status: Preparing" in messages[3]["content"]
    assert all("{" not in message["content"] for message in messages)


def test_cancel_confirmation_summary(client):
    order(client)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        action_id = agent.prepare(db, sid, user, "cancel_order", {"order_id": 1})["pending_action_id"]
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json()["outcome"]["status"] == "CANCELLED"
    message = client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()[0]["content"]
    assert "Your order has been cancelled." in message
    assert "Order #1" in message and "Status: Cancelled" in message
    assert "{" not in message


def test_cancel_only_requested_portions_and_preserve_other_dishes(client):
    with SessionLocal.begin() as db:
        db.add(MenuItem(title="Tomato Soup", category="Starter", vegetarian=True, price="80.00", capacity=4))
    data = {"lines": [{"item_id": 1, "quantity": 1}, {"item_id": 2, "quantity": 2}]}
    assert order(client, data=data).status_code == 201
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    def chat(text):
        return client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": text}).json()
    assert "How many" in chat("cancel tomato soup")["message"]
    assert client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json() == []
    result = chat("1")
    action_id = result["pending_action_id"]
    preview = client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json()[0]["preview"]
    assert preview["title"] == "Tomato Soup" and preview["quantity"] == 1
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=BOB, json={"confirm": True}).status_code == 404
    first = client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json()
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json() == first
    assert first["outcome"]["remaining_total"] == "170.00"
    saved = client.get("/api/orders", auth=ALICE).json()[0]
    assert saved["status"] == "CONFIRMED" and saved["remaining_total"] == "170.00"
    assert [line["cancelled_quantity"] for line in saved["lines"]] == [0, 1]
    assert client.get("/api/menu_items/2").json()["capacity"] == 3
    assert client.post("/api/orders/1/cancel", auth=ALICE).json()["status"] == "CANCELLED"
    assert client.get("/api/menu_items/2").json()["capacity"] == 4
    assert client.get("/api/menu_items/1").json()["capacity"] == 2
    assert client.get("/api/orders", auth=ALICE).json()[0]["remaining_total"] == "0"


def test_item_cancellation_stale_preview_and_multiple_orders(client):
    assert order(client).status_code == 201
    assert order(client, "second").status_code == 201
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    def chat(text):
        return client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": text}).json()
    assert "multiple orders" in chat("cancel dosa")["message"]
    first = chat("cancel dosa from order 1")["pending_action_id"]
    second = chat("cancel dosa from order 1")["pending_action_id"]
    assert client.post(f"/api/chat/actions/{first}/confirm", auth=ALICE, json={"confirm": True}).status_code == 200
    assert client.post(f"/api/chat/actions/{second}/confirm", auth=ALICE, json={"confirm": True}).status_code == 409
    orders = client.get("/api/orders", auth=ALICE).json()
    assert orders[0]["status"] == "CONFIRMED" and orders[1]["status"] == "CANCELLED"


def test_whole_order_preview_rechecks_partial_cancellation(client):
    with SessionLocal.begin() as db:
        db.add(MenuItem(title="Tomato Soup", category="Starter", vegetarian=True, price="80.00", capacity=4))
    data = {"lines": [{"item_id": 1, "quantity": 1}, {"item_id": 2, "quantity": 1}]}
    assert order(client, data=data).status_code == 201
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    def chat(text):
        return client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": text}).json()
    whole = chat("cancel order 1")["pending_action_id"]
    actions = client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json()
    assert {line["title"] for line in actions[0]["preview"]["lines"]} == {"Masala Dosa", "Tomato Soup"}
    item = chat("cancel tomato soup from order 1")["pending_action_id"]
    assert client.post(f"/api/chat/actions/{item}/confirm", auth=ALICE, json={"confirm": True}).status_code == 200
    assert client.post(f"/api/chat/actions/{whole}/confirm", auth=ALICE, json={"confirm": True}).status_code == 409
    assert client.get("/api/orders", auth=ALICE).json()[0]["status"] == "CONFIRMED"
    assert client.get("/api/menu_items/1").json()["capacity"] == 1


def test_menu_filters_combine(client):
    with SessionLocal.begin() as db:
        db.add_all([
            MenuItem(title="Egg Dosa", category="Breakfast", vegetarian=False, price="95.00", capacity=4),
            MenuItem(title="Mango Lassi", category="Drink", vegetarian=True, price="75.00", capacity=4),
            MenuItem(title="Special Dosa", category="Breakfast", vegetarian=True, price="150.00", capacity=4),
        ])
    result = client.get("/api/menu_items", params={"keyword": "Dosa", "category": "Breakfast",
                                                   "vegetarian": True, "max_price": 100}).json()
    assert [item["title"] for item in result] == ["Masala Dosa"]


def test_extra_menu_items_cover_categories_and_preserve_existing(client):
    assert {row[1] for row in EXTRA_ITEMS} == {row[1] for row in BASE_ITEMS}
    with SessionLocal.begin() as db:
        db.add(MenuItem(title="plain dosa", category="Custom", vegetarian=True,
                        price="99.00", capacity=3, active=False))
    with SessionLocal.begin() as db:
        assert add_extra_items(db) == len(EXTRA_ITEMS) - 1
    with SessionLocal.begin() as db:
        assert add_extra_items(db) == 0
        existing = db.query(MenuItem).filter_by(title="plain dosa").one()
        assert existing.category == "Custom" and str(existing.price) == "99.00"
        assert existing.capacity == 3 and not existing.active
        assert db.query(MenuItem).count() == len(EXTRA_ITEMS) + 1
    menu = client.get("/api/menu_items", params={"category": "Dessert"}).json()
    assert {item["title"] for item in menu} == {"Rasmalai", "Rasgulla", "Kheer", "Kulfi"}


def test_seeded_menu_photos_are_present_and_credited(client):
    static = Path(__file__).resolve().parents[1] / "static"
    photos = json.loads((static / "images/menu/photos.json").read_text())
    assert set(photos) == {item[0] for item in ITEMS}
    for photo in photos.values():
        assert photo["author"] and photo["license"].startswith("CC BY")
        assert photo["source"].startswith("https://commons.wikimedia.org/")
        assert photo["license_url"].startswith("https://creativecommons.org/licenses/")
        path = static / photo["path"].removeprefix("/static/")
        assert path.read_bytes().startswith(b"\xff\xd8\xff")
        assert client.get(photo["path"]).status_code == 200


def test_chat_menu_uses_database_categories(client, monkeypatch):
    monkeypatch.setattr(agent, "api_get", lambda path, auth, params=None: client.get(path, params=params, auth=auth).json())
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "show menu"}).json()
    assert "Masala Dosa (Breakfast): INR 90.00" in result["message"]
    assert "Main course" not in result["message"]


@pytest.mark.parametrize("text", [
    "number of items in menu", "How many items are in the menu?",
    "How many dishes do you have?", "count menu items", "total number of items on your menu",
])
def test_chat_menu_count_uses_live_active_menu(client, monkeypatch, text):
    with SessionLocal.begin() as db:
        db.add_all([
            MenuItem(title="Soup", category="Starter", vegetarian=True, price="80.00", capacity=4),
            MenuItem(title="Inactive", category="Starter", vegetarian=True, price="50.00", capacity=4, active=False),
        ])
    assert order(client).status_code == 201
    monkeypatch.setattr(agent, "client", lambda: pytest.fail("AI should not be called for menu counts"))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": text})
    assert response.status_code == 200
    assert response.json()["message"] == "There are 2 active items on the menu."
    assert response.json()["pending_action_id"] is None
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()[-1]["content"] == response.json()["message"]


def test_menu_count_does_not_match_orders_or_filtered_menu():
    assert not agent.is_menu_count_request("how many orders do I have?")
    assert not agent.is_menu_count_request("how many vegetarian items are in the menu?")
    assert not agent.is_menu_count_request("order 2 items from the menu")


def test_chat_order_history_uses_live_user_orders(client, monkeypatch):
    with SessionLocal.begin() as db:
        db.add(MenuItem(title="Mango Lassi", category="Drink", vegetarian=True, price="75.00", capacity=4))
    assert order(client).status_code == 201
    assert order(client, "second", data={"lines": [{"item_id": 2, "quantity": 2}]}).status_code == 201
    assert order(client, "bob", auth=BOB).status_code == 201
    monkeypatch.setattr(agent, "api_get", lambda path, auth, params=None: client.get(path, auth=auth).json())
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                           json={"message": "show my all previous orders"})
    assert response.status_code == 200
    answer = response.json()["message"]
    assert "Order #2" in answer and "Mango Lassi (Drink): 2 × INR 75.00" in answer
    assert "Order #1" in answer and "Masala Dosa (Breakfast): 1 × INR 90.00" in answer
    assert "Order #3" not in answer and "Remaining total: INR 150.00" in answer
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()[-1]["content"] == answer


def test_order_history_does_not_trust_model_without_read_tool(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: ChatCompletionMessage(
        role="assistant", content="Order #4: Imaginary Soup, INR 80"))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                           json={"message": "show previous orders from yesterday"})
    assert response.status_code == 200
    assert "couldn't retrieve" in response.json()["message"]
    assert "Imaginary Soup" not in response.json()["message"]


def test_order_history_tool_result_is_not_rewritten_by_model(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    assert order(client).status_code == 201
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(agent, "api_get", lambda path, auth, params=None: client.get(path, auth=auth).json())
    response = ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [
        {"id": "tool-1", "type": "function", "function": {"name": "list_orders", "arguments": "{}"}}]})
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: response)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE,
                         json={"message": "what have I ordered before?"}).json()
    assert "Order #1" in result["message"] and "Masala Dosa (Breakfast): 1 × INR 90.00" in result["message"]


def test_chat_rejects_wrong_dish_after_yes(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    with SessionLocal.begin() as db:
        db.add_all([
            MenuItem(title="Mango Lassi", category="Drink", vegetarian=True, price="75.00", capacity=4),
            MenuItem(title="Tomato Soup", category="Starter", vegetarian=True, price="80.00", capacity=4),
        ])
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        agent.append_message(db, sid, user.id, "user", "order lassi", {})
        agent.append_message(db, sid, user.id, "assistant", "Would you like Mango Lassi?", {})
    response = ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [
        {"id": "tool-1", "type": "function", "function": {
            "name": "create_order", "arguments": '{"lines":[{"item_id":3,"quantity":1}]}'}}]})
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: response)
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "yes"})
    assert result.status_code == 200
    assert "No order was prepared" in result.json()["message"]
    assert result.json()["pending_action_id"] is None
    assert client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json() == []
    assert client.get("/api/orders", auth=ALICE).json() == []


def test_requested_item_matching_handles_ambiguity_and_typos():
    items = [MenuItem(id=1, title="Mango Lassi"), MenuItem(id=2, title="Tomato Soup"),
             MenuItem(id=3, title="Chicken Soup"), MenuItem(id=4, title="Masala Dosa")]
    assert agent.mentioned_items("order lassi", items) == ({1}, False)
    assert agent.mentioned_items("order mango lassi and masala dosa", items) == ({1, 4}, False)
    assert agent.mentioned_items("order soup", items) == ({2, 3}, True)
    assert agent.mentioned_items("order tomato soup", items) == ({2}, False)
    assert agent.mentioned_items("order lasssi", items) == ({1}, False)
    assert agent.mentioned_items("order please", items) == (set(), False)


def test_correct_dish_after_yes_can_be_confirmed(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    with SessionLocal.begin() as db:
        db.add(MenuItem(title="Mango Lassi", category="Drink", vegetarian=True, price="75.00", capacity=4))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(username="alice").one()
        agent.append_message(db, sid, user.id, "user", "order lassi", {})
        agent.append_message(db, sid, user.id, "assistant", "Would you like Mango Lassi?", {})
    response = ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [
        {"id": "tool-1", "type": "function", "function": {
            "name": "create_order", "arguments": '{"lines":[{"item_id":2,"quantity":1}]}'}}]})
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: response)
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "yes"}).json()
    action_id = result["pending_action_id"]
    assert client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json()[0]["preview"]["lines"][0]["title"] == "Mango Lassi"
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json()["outcome"]["total"] == "75.00"


def test_agent_tool_call_and_history(client, monkeypatch):
    class Message:
        def __init__(self, tool_calls, content=None):
            self.tool_calls, self.content = tool_calls, content

        def model_dump(self, **kwargs):
            return {"role": "assistant", "content": self.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in self.tool_calls]}

    call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="create_order",
                           arguments='{"lines":[{"item_id":1,"quantity":1}]}'))
    responses = iter([Message([call]), Message([], "Please confirm the order.")])
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=next(responses))]))))
    monkeypatch.setattr(agent, "client", lambda: fake)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "Order a dosa"})
    assert response.status_code == 200
    assert response.json()["mode"] == "AGENT"
    assert response.json()["pending_action_id"]
    assert len(client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json()) == 1
    assert client.get("/api/orders", auth=ALICE).json() == []
    history = client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_gemini_tool_call_and_confirmation(client, monkeypatch):
    import json
    import httpx
    from openai import OpenAI

    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert body["model"] == "gemini-3.8-flash"
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {
                    "name": "create_order", "arguments": json.dumps(LINE)},
                 "extra_content": {"google": {"thought_signature": "test-signature"}}}]}
        else:
            assert body["messages"][-2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "test-signature"
            assert json.loads(body["messages"][-1]["content"])["pending_action_id"]
            message = {"role": "assistant", "content": "Please confirm your order."}
        return httpx.Response(200, json={"id": "chat-test", "object": "chat.completion", "created": 1,
                                        "model": "gemini-3.8-flash",
                                        "choices": [{"index": 0, "finish_reason": "stop", "message": message}]})

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(ai_provider, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "Order a dosa"})
    assert response.status_code == 200
    assert len(requests) == 2
    assert client.get("/api/orders", auth=ALICE).json() == []
    action_id = response.json()["pending_action_id"]
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).json()["status"] == "CONFIRMED"
    assert len(client.get("/api/orders", auth=ALICE).json()) == 1


def test_typo_menu_search_only_suggests_matches(monkeypatch):
    calls = []
    def fake_get(path, auth, params=None):
        calls.append(params)
        if params.get("keyword"):
            return []
        return [{"id": 1, "title": "Masala Dosa", "capacity": 2, "price": "90.00"}]
    monkeypatch.setattr(agent, "api_get", fake_get)
    result = agent.run_tool(None, 1, None, ALICE, "search_menu_items", {"keyword": "masla dosa"})
    assert result["items"] == []
    assert result["suggestions"][0]["title"] == "Masala Dosa"
    assert "uncertain" in result["message"]
    assert calls == [{"keyword": "masla dosa"}, {}]


def test_gemini_fallback_rolls_back_pending_action(client, monkeypatch):
    import json
    import httpx
    from openai import OpenAI

    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        if len(calls) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-1", "type": "function", "function": {
                    "name": "create_order", "arguments": json.dumps(LINE)}}]}
        elif len(calls) == 2:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        else:
            message = {"role": "assistant", "content": "Please specify what you would like."}
        return httpx.Response(200, json={"id": "chat-test", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": message}]})

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(ai_provider, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "order dosa"})
    assert result.status_code == 200
    assert result.json()["fallback_used"] is True
    assert calls == ["primary", "primary", "backup"]
    assert client.get(f"/api/chat/sessions/{sid}/actions", auth=ALICE).json() == []
    assert client.get("/api/orders", auth=ALICE).json() == []


def test_gemini_reports_rate_limit_when_both_models_fail(client, monkeypatch):
    import json
    import httpx
    from openai import OpenAI

    calls = []
    def handle(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(429, json={"error": {"message": "rate limited"}})
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "primary")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(ai_provider, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    result = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "list my oders"})
    assert result.status_code == 429
    assert result.json()["code"] == "AI_RATE_LIMIT"
    assert calls == ["primary", "backup"]
    assert client.get("/api/orders", auth=ALICE).json() == []
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()[-1]["details"]["mode"] == "ERROR"


def test_ai_provider_configuration(monkeypatch, tmp_path):
    from fastapi import HTTPException

    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(HTTPException, match="GEMINI_API_KEY"):
        ai_provider.client()
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path))
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    gemini_collection = rag.collection().name
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    assert rag.collection().name == "food_policies"
    assert gemini_collection != rag.collection().name
    monkeypatch.setenv("AI_PROVIDER", "unsupported")
    with pytest.raises(HTTPException, match="AI_PROVIDER"):
        ai_provider.provider()


def test_ollama_native_tool_turns_and_local_configuration(monkeypatch):
    seen = []
    def fake_post(url, *, json, timeout, trust_env):
        assert url == "http://127.0.0.1:11434/api/chat"
        assert json["think"] is False
        assert trust_env is False
        seen.append(json)
        if len(seen) == 1:
            data = {"message": {"role": "assistant", "tool_calls": [
                {"function": {"name": "list_orders", "arguments": {}}}]}}
        else:
            assert json["messages"][-1]["tool_name"] == "list_orders"
            assert json["messages"][-2]["tool_calls"][0]["function"]["arguments"] == {}
            data = {"message": {"role": "assistant", "content": "No orders."}}
        return SimpleNamespace(is_success=True, json=lambda: data)
    monkeypatch.setattr(ai_provider.httpx, "post", fake_post)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    assert ai_provider.chat_model() == "qwen2.5:3b"
    assert ai_provider.embedding_model() == "nomic-embed-text"
    message = ai_provider.ollama_chat("qwen3:4b", [{"role": "user", "content": "list my orders"}], agent.TOOLS)
    call = message.tool_calls[0]
    messages = [{"role": "user", "content": "list my orders"}, message.model_dump(exclude_none=True),
                {"role": "tool", "tool_call_id": call.id, "content": '{"orders": []}'}]
    assert ai_provider.ollama_chat("qwen3:4b", messages, agent.TOOLS).content == "No orders."


def test_ollama_empty_reply_retries_and_write_is_pending(client, monkeypatch):
    from openai.types.chat import ChatCompletionMessage

    responses = iter([
        ChatCompletionMessage(role="assistant", content=None),
        ChatCompletionMessage.model_validate({"role": "assistant", "content": None, "tool_calls": [
            {"id": "tool-1", "type": "function", "function": {
                "name": "create_order", "arguments": '{"lines":[{"item_id":1,"quantity":1}]}'}}]}),
    ])
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(agent, "ollama_chat", lambda *args: next(responses))
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "order dosa"})
    assert response.status_code == 200
    assert "No changes have been made yet" in response.json()["message"]
    assert response.json()["pending_action_id"]
    assert client.get("/api/orders", auth=ALICE).json() == []


def test_gemini_document_index_and_retrieval(client, monkeypatch, tmp_path):
    import json
    import httpx
    from openai import OpenAI

    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/embeddings")
        assert body["model"] == "gemini-embedding-001"
        return httpx.Response(200, json={"object": "list", "model": body["model"],
            "data": [{"object": "embedding", "index": i, "embedding": [1.0, 0.0, 0.0]}
                     for i in range(len(body["input"]))], "usage": {"prompt_tokens": 1, "total_tokens": 1}})
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path))
    monkeypatch.setattr(ai_provider, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))))
    upload = client.post("/api/documents", auth=ADMIN,
                         files={"file": ("policy.txt", b"Cancellation before preparation.", "text/plain")})
    assert upload.status_code == 201
    with SessionLocal() as db:
        result = rag.retrieve(db, "cancellation")
    assert result[0]["source"] == "policy.txt"
    assert result[0]["page"] == 1
    assert len(requests) == 2


def test_unavailable_ai_persists_failure(client, monkeypatch):
    from fastapi import HTTPException

    def unavailable():
        raise HTTPException(503, "AI unavailable")
    monkeypatch.setattr(agent, "client", unavailable)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    assert client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "hello"}).status_code == 503
    assert [m["details"].get("mode") for m in client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()] == [None, "ERROR"]


def test_ai_quota_error_message(client, monkeypatch):
    import httpx
    from openai import RateLimitError

    def exhausted():
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com"))
        raise RateLimitError("quota exhausted", response=response,
                             body={"type": "insufficient_quota", "code": "credit_balance_exhausted"})
    monkeypatch.setattr(agent, "client", exhausted)
    sid = client.post("/api/chat/sessions", auth=ALICE).json()["id"]
    response = client.post(f"/api/chat/sessions/{sid}/messages", auth=ALICE, json={"message": "hello"})
    assert response.status_code == 429
    assert response.json()["code"] == "AI_QUOTA_EXHAUSTED"
    assert "billing" in response.json()["message"]
    assert client.get(f"/api/chat/sessions/{sid}/messages", auth=ALICE).json()[-1]["details"]["mode"] == "ERROR"


def test_document_index_and_retrieval(client, monkeypatch):
    entries = {}
    class Collection:
        def add(self, ids, documents, metadatas, embeddings):
            entries.update(zip(ids, zip(documents, metadatas)))
        def query(self, **kwargs):
            key = next(iter(entries))
            text, meta = entries[key]
            return {"ids": [[key]], "documents": [[text]], "metadatas": [[meta]], "distances": [[0.1]]}
    fake = SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs:
        SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0, 0.0]) for i, _ in enumerate(kwargs["input"])])))
    monkeypatch.setattr(rag, "client", lambda: fake)
    monkeypatch.setattr(rag, "collection", lambda: Collection())
    upload = client.post("/api/documents", auth=ADMIN, files={"file": ("policy.txt", b"Cancellation before preparation.", "text/plain")})
    assert upload.status_code == 201
    assert client.post("/api/documents", auth=ALICE, files={"file": ("policy.txt", b"test")}).status_code == 403
    with SessionLocal() as db:
        result = rag.retrieve(db, "cancellation")
        assert result[0]["source"] == "policy.txt"
        assert result[0]["page"] == 1


def test_rate_limiter_separates_clients_and_buckets():
    limiter = RateLimiter()
    assert limiter.allow("client-a", "ai", 2)
    assert limiter.allow("client-a", "ai", 2)
    assert not limiter.allow("client-a", "ai", 2)
    assert limiter.allow("client-a", "general", 2)
    assert limiter.allow("client-b", "ai", 2)


@pytest.mark.skipif(engine.dialect.name != "mysql", reason="requires dedicated MySQL test database")
def test_mysql_concurrent_last_portion(client):
    with SessionLocal.begin() as db:
        db.get(MenuItem, 1).capacity = 1
    def make_order(args):
        auth, key = args
        with TestClient(app) as c:
            return order(c, key=key, auth=auth).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(make_order, [(ALICE, "one"), (BOB, "two")]))
    assert statuses == [201, 409]
    assert client.get("/api/menu_items/1").json()["capacity"] == 0
