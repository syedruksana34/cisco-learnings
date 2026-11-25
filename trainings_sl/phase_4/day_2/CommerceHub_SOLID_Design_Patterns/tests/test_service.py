from app.models import OrderRequest
from app.repository import InMemoryOrderRepository
from app.service import OrderService


def build_sample_order() -> OrderRequest:
    return OrderRequest(
        customer_name="Anu",
        items=[
            {"name": "Notebook", "quantity": 2, "unit_price": 50},
            {"name": "Pen", "quantity": 1, "unit_price": 20},
        ],
    )


def test_calculate_total_returns_120() -> None:
    service = OrderService(InMemoryOrderRepository())

    assert service.calculate_total(build_sample_order()) == 120.0


def test_created_order_can_be_listed() -> None:
    service = OrderService(InMemoryOrderRepository())
    request = build_sample_order()

    created_order = service.create_order(request)

    assert created_order.order_id == 1
    assert service.list_orders() == [created_order]