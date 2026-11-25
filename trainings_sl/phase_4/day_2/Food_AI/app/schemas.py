from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128, pattern=r"^[\x20-\x7E]+$")


class ItemCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    vegetarian: bool
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    capacity: int = Field(ge=0)
    active: bool = True


class ItemResponse(ItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class Line(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=10)


class OrderCreate(BaseModel):
    lines: Annotated[list[Line], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def unique_items(self):
        if len({line.item_id for line in self.lines}) != len(self.lines):
            raise ValueError("Each item may occur only once")
        return self


class StatusUpdate(BaseModel):
    status: str


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConfirmRequest(BaseModel):
    confirm: bool
