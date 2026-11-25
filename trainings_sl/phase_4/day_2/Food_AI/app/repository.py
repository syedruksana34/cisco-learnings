from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ChatSession, MenuItem, Order


class Repository:
    def __init__(self, db: Session):
        self.db = db

    def item(self, item_id: int, lock: bool = False):
        query = select(MenuItem).where(MenuItem.id == item_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)

    def order(self, order_id: int, lock: bool = False):
        query = select(Order).where(Order.id == order_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)

    def chat(self, session_id: int, user_id: int, lock: bool = False):
        query = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)
