"""Storage layer: manages orders in memory for this hands-on."""

from typing import Protocol

from app.models import OrderResponse


class OrderRepository(Protocol):
    """Contract for order persistence used by the service layer."""

    def save(self, order: OrderResponse) -> OrderResponse:
        ...

    def list_all(self) -> list[OrderResponse]:
        ...


class InMemoryOrderRepository:
    """Assign IDs and manage the in-memory order collection."""

    def __init__(self) -> None:
        self._orders: list[OrderResponse] = []
        self._next_order_id = 1

    def save(self, order: OrderResponse) -> OrderResponse:
        """Assign the next sequential ID and store the order."""
        order.order_id = self._next_order_id
        self._next_order_id += 1
        self._orders.append(order)
        return order

    def list_all(self) -> list[OrderResponse]:
        return list(self._orders)