from .database import engine
from .models import ItemCancellation, OrderFeedback


def main():
    ItemCancellation.__table__.create(engine, checkfirst=True)
    OrderFeedback.__table__.create(engine, checkfirst=True)
    print("Item cancellation and order feedback tables are ready. Existing orders were preserved.")


if __name__ == "__main__":
    main()
