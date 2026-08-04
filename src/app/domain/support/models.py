"""Persisted customer-support models."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ORDER_STATUSES = ("pending", "processing", "shipped", "delivered", "cancelled", "refunded")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            f"status IN {ORDER_STATUSES}",
            name="ck_orders_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_amount_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        index=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            f"status IN {TICKET_STATUSES}",
            name="ck_tickets_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id"),
        index=True,
    )
    order_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("orders.id"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(20),
        default="open",
        server_default="open",
        index=True,
    )


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    __table_args__ = (
        UniqueConstraint("slug", "version", name="uq_policy_documents_slug_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
