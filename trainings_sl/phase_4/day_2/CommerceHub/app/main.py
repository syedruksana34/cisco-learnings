"""API layer: exposes CommerceHub HTTP endpoints."""

from fastapi import FastAPI, status

from app.models import OrderRequest, OrderResponse
from app.repository import OrderRepository
from app.service import OrderService

app = FastAPI(title="CommerceHub Orders API")

# A shared service and repository keep orders available across requests.
order_service = OrderService(OrderRepository())


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple API availability response."""
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_request: OrderRequest) -> OrderResponse:
    """Pass validated request data to the business-logic layer."""
    return order_service.create_order(order_request)


@app.get("/orders", response_model=list[OrderResponse])
def list_orders() -> list[OrderResponse]:
    return order_service.list_orders()