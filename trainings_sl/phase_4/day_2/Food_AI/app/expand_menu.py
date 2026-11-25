from .database import SessionLocal
from .seed import add_extra_items


def main():
    with SessionLocal.begin() as db:
        added = add_extra_items(db)
    print(f"Added {added} menu items. Existing items and orders were preserved.")


if __name__ == "__main__":
    main()
