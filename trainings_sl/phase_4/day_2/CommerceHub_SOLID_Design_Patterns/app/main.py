"""API layer: exposes CommerceHub HTTP endpoints."""

from fastapi import Depends, FastAPI, status

from app.models import OrderRequest, OrderResponse
from app.repository import InMemoryOrderRepository
from app.service import OrderService

app = FastAPI(title="CommerceHub Orders API")

_order_service = OrderService(InMemoryOrderRepository())


def get_order_service() -> OrderService:
    """Provide the shared service so orders persist across requests."""
    return _order_service


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple API availability response."""
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order_request: OrderRequest,
    order_service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    """Pass validated request data to the business-logic layer."""
    return order_service.create_order(order_request)


@app.get("/orders", response_model=list[OrderResponse])
def list_orders(
    order_service: OrderService = Depends(get_order_service),
) -> list[OrderResponse]:
    return order_service.list_orders()