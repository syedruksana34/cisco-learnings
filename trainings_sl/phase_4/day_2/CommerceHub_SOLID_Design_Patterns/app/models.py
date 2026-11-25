"""Data-model layer: validates request data and defines responses."""

from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    """One product contained in an order."""
    name: str
    quantity: int = Field(gt=0)  # Quantity must be positive.
    unit_price: float = Field(ge=0)  # Price cannot be negative.


class OrderRequest(BaseModel):
    """Client payload for creating an order."""
    customer_name: str
    items: list[OrderItem] = Field(min_length=1)


class OrderResponse(BaseModel):
    """Order data returned to the client."""
    order_id: int
    customer_name: str
    items: list[OrderItem]
    total: float 