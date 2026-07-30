"""Validated commands and public support-domain responses."""

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)


class CustomerRead(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class OrderCreate(BaseModel):
    customer_id: UUID
    status: OrderStatus = OrderStatus.PENDING
    total_amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class OrderRead(OrderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class TicketCreate(BaseModel):
    customer_id: UUID
    order_id: UUID | None = None
    subject: str = Field(min_length=1, max_length=300)
    status: TicketStatus = TicketStatus.OPEN


class TicketRead(TicketCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
