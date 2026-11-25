"""Business-logic layer: processes order data before storage."""
"""Calculating order totals and coordinating with the repository."""

from app.models import OrderRequest, OrderResponse
from app.repository import OrderRepository


class OrderService:
    """Coordinates order creation and retrieval."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def create_order(self, order_request: OrderRequest) -> OrderResponse:
        """Calculate the total and delegate saving to the repository."""
        total = round(
            sum(item.quantity * item.unit_price for item in order_request.items),
            2,
        )
        order = OrderResponse(
            order_id=0,  # The repository replaces this placeholder with the real ID.
            customer_name=order_request.customer_name,
            items=order_request.items,
            total=total,
        )
        return self._repository.save(order)

    def list_orders(self) -> list[OrderResponse]:
        return self._repository.list_all()