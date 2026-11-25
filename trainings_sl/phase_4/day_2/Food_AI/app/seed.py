import os

from sqlalchemy import func, select

from .database import Base, SessionLocal, engine
from .models import MenuItem, User
from .schemas import OrderCreate
from .security import hasher
from .service import FoodService

BASE_ITEMS = [
    ("Masala Dosa", "Breakfast", True, "90.00", 20),
    ("Paneer Biryani", "Main course", True, "180.00", 10),
    ("Idli Sambar", "Breakfast", True, "70.00", 20),
    ("Vegetable Pulao", "Main course", True, "150.00", 12),
    ("Dal Tadka", "Main course", True, "130.00", 15),
    ("Chicken Biryani", "Main course", False, "220.00", 10),
    ("Egg Curry", "Main course", False, "160.00", 10),
    ("Tomato Soup", "Starter", True, "80.00", 15),
    ("Gulab Jamun", "Dessert", True, "60.00", 20),
    ("Mango Lassi", "Drink", True, "75.00", 20),
]

EXTRA_ITEMS = [
    ("Plain Dosa", "Breakfast", True, "70.00", 20),
    ("Onion Uttapam", "Breakfast", True, "100.00", 15),
    ("Medu Vada", "Breakfast", True, "65.00", 20),
    ("Poha", "Breakfast", True, "60.00", 20),
    ("Palak Paneer", "Main course", True, "170.00", 15),
    ("Chole Masala", "Main course", True, "140.00", 15),
    ("Chicken Curry", "Main course", False, "210.00", 12),
    ("Rajma Masala", "Main course", True, "145.00", 15),
    ("Vegetable Samosa", "Starter", True, "55.00", 20),
    ("Paneer Tikka", "Starter", True, "160.00", 12),
    ("Chicken Tikka", "Starter", False, "190.00", 12),
    ("Vegetable Pakora", "Starter", True, "80.00", 18),
    ("Rasmalai", "Dessert", True, "90.00", 15),
    ("Rasgulla", "Dessert", True, "70.00", 20),
    ("Kheer", "Dessert", True, "85.00", 15),
    ("Kulfi", "Dessert", True, "80.00", 15),
    ("Sweet Lassi", "Drink", True, "65.00", 20),
    ("Masala Chai", "Drink", True, "40.00", 25),
    ("Fresh Lime Soda", "Drink", True, "55.00", 20),
    ("Filter Coffee", "Drink", True, "50.00", 20),
]
ITEMS = BASE_ITEMS + EXTRA_ITEMS


def add_extra_items(db):
    existing = {title.strip().casefold() for title in db.scalars(select(MenuItem.title)).all()}
    added = 0
    for title, category, vegetarian, price, capacity in EXTRA_ITEMS:
        if title.casefold() not in existing:
            db.add(MenuItem(title=title, category=category, vegetarian=vegetarian, price=price, capacity=capacity))
            existing.add(title.casefold())
            added += 1
    return added


def main():
    password = os.getenv("DEMO_PASSWORD")
    if not password or len(password) < 12:
        raise SystemExit("Set DEMO_PASSWORD to at least 12 characters before seeding.")
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        for username, role in (("admin", "admin"), ("alice", "user"), ("bob", "user")):
            if not db.scalar(select(User).where(User.username == username)):
                db.add(User(username=username, password_hash=hasher.hash(password), role=role))
        if not db.scalar(select(func.count()).select_from(MenuItem)):
            db.add_all([MenuItem(title=t, category=c, vegetarian=v, price=p, capacity=n)
                        for t, c, v, p, n in ITEMS])
            db.flush()
            alice = db.scalar(select(User).where(User.username == "alice"))
            bob = db.scalar(select(User).where(User.username == "bob"))
            for user, title, key in ((alice, "Masala Dosa", "seed-dosa"),
                                     (bob, "Paneer Biryani", "seed-biryani"),
                                     (alice, "Idli Sambar", "seed-idli")):
                item = db.scalar(select(MenuItem).where(MenuItem.title == title))
                FoodService(db).create_order(OrderCreate.model_validate(
                    {"lines": [{"item_id": item.id, "quantity": 1}]}), user, key)
    print("Schema and fictional users/menu initialized. Existing records were preserved.")


if __name__ == "__main__":
    main()
