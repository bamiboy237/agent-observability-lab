"""This module defines validated commands and public responses for customer support."""

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
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "e5afa83a-25c7-5b71-98bb-b8eae0d188c0",
                    "customer_id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
                    "status": "delivered",
                    "total_amount": "48.25",
                }
            ]
        },
    )

    id: UUID


class TicketCreate(BaseModel):
    customer_id: UUID
    order_id: UUID | None = None
    subject: str = Field(min_length=1, max_length=300)
    status: TicketStatus = TicketStatus.OPEN


class TicketRead(TicketCreate):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "customer_id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
                    "order_id": "e5afa83a-25c7-5b71-98bb-b8eae0d188c0",
                    "subject": "Where is my order?",
                    "status": "open",
                }
            ]
        },
    )

    id: UUID


class CreateTicketCommand(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "actor_id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
                    "order_id": "e5afa83a-25c7-5b71-98bb-b8eae0d188c0",
                    "subject": "Where is my order?",
                }
            ]
        }
    )

    actor_id: UUID
    order_id: UUID | None = None
    subject: str = Field(min_length=1, max_length=300)


class RefundCommand(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "actor_id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
                    "order_id": "e5afa83a-25c7-5b71-98bb-b8eae0d188c0",
                }
            ]
        }
    )

    actor_id: UUID
    order_id: UUID


class PolicyDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    version: str
    title: str
    content: str
    content_hash: str
