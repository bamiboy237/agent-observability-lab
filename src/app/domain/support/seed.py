"""This module defines deterministic seed data for the support domain."""

from hashlib import sha256
from typing import TypedDict
from uuid import UUID, uuid5

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.support.models import Customer, Order, PolicyDocument

SEED_NAMESPACE = UUID("30f66e1b-9d4e-4a6c-a1c7-28d473ef4076")


def seed_id(name: str) -> UUID:
    """This function returns the stable UUID for one named seed record."""
    return uuid5(SEED_NAMESPACE, name)


class CustomerSeed(TypedDict):
    id: UUID
    name: str
    email: str


class OrderSeed(TypedDict):
    id: UUID
    customer_id: UUID
    status: str
    total_amount: str


class PolicyDocumentSeed(TypedDict):
    id: UUID
    slug: str
    version: str
    title: str
    content: str
    content_hash: str


CUSTOMERS: tuple[CustomerSeed, ...] = (
    {
        "id": seed_id("customer:alex-rivera"),
        "name": "Alex Rivera",
        "email": "alex.rivera@example.test",
    },
    {
        "id": seed_id("customer:samira-patel"),
        "name": "Samira Patel",
        "email": "samira.patel@example.test",
    },
)

ORDERS: tuple[OrderSeed, ...] = tuple(
    {
        "id": seed_id(f"order:{status}"),
        "customer_id": CUSTOMERS[index % len(CUSTOMERS)]["id"],
        "status": status,
        "total_amount": amount,
    }
    for index, (status, amount) in enumerate(
        (
            ("pending", "24.99"),
            ("processing", "79.50"),
            ("shipped", "135.00"),
            ("delivered", "48.25"),
            ("cancelled", "19.95"),
            ("refunded", "210.00"),
        )
    )
)

POLICY_CONTENT = """# Refund and Delivery Policy

Policy version: 2026-07-30

Customers may request a refund within 30 days after delivery. Delivered orders
are eligible when the item is unused or defective. Shipped orders cannot be
refunded until delivery is confirmed. Cancelled orders require no refund unless
payment was captured. Approved refunds return to the original payment method.

Support agents must confirm the customer's email and order identifier before
disclosing order details or changing an order. Any exception requires human
review and a note on the support ticket.
"""

POLICY_DOCUMENTS: tuple[PolicyDocumentSeed, ...] = (
    {
        "id": seed_id("policy:refund-and-delivery:2026-07-30"),
        "slug": "refund-and-delivery",
        "version": "2026-07-30",
        "title": "Refund and Delivery Policy",
        "content": POLICY_CONTENT,
        "content_hash": sha256(POLICY_CONTENT.encode()).hexdigest(),
    },
)


class SeedSummary(BaseModel):
    customer_count: int
    order_count: int
    policy_document_count: int
    customer_ids: tuple[UUID, ...]
    order_ids: tuple[UUID, ...]
    policy_document_ids: tuple[UUID, ...]
    policy_content_hashes: tuple[str, ...]


async def seed_support_data(session: AsyncSession) -> SeedSummary:
    """This function inserts missing seed records and preserves existing records."""
    await session.execute(insert(Customer).values(CUSTOMERS).on_conflict_do_nothing())
    await session.execute(insert(Order).values(ORDERS).on_conflict_do_nothing())
    await session.execute(
        insert(PolicyDocument).values(POLICY_DOCUMENTS).on_conflict_do_nothing()
    )
    await session.flush()

    customer_ids = tuple(record["id"] for record in CUSTOMERS)
    order_ids = tuple(record["id"] for record in ORDERS)
    policy_document_ids = tuple(record["id"] for record in POLICY_DOCUMENTS)

    customer_count = await session.scalar(
        select(func.count()).select_from(Customer).where(Customer.id.in_(customer_ids))
    )
    order_count = await session.scalar(
        select(func.count()).select_from(Order).where(Order.id.in_(order_ids))
    )
    policy_documents = (
        await session.execute(
            select(PolicyDocument.id, PolicyDocument.content_hash)
            .where(PolicyDocument.id.in_(policy_document_ids))
            .order_by(PolicyDocument.id)
        )
    ).all()

    return SeedSummary(
        customer_count=customer_count or 0,
        order_count=order_count or 0,
        policy_document_count=len(policy_documents),
        customer_ids=customer_ids,
        order_ids=order_ids,
        policy_document_ids=policy_document_ids,
        policy_content_hashes=tuple(row.content_hash for row in policy_documents),
    )
