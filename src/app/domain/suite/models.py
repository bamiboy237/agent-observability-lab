"""This module defines the model that stores immutable regression suite versions."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RegressionSuiteRecord(Base):
    """This class stores one immutable version of one case suite.

    The suite id is stable for one suite name; the suite version increases
    whenever the member set changes. History is never overwritten: each
    member set is stored at most once per suite.
    """

    __tablename__ = "regression_suites"
    __table_args__ = (
        UniqueConstraint(
            "suite_id",
            "suite_version",
            name="uq_regression_suites_suite_version",
        ),
        UniqueConstraint(
            "suite_id",
            "members_hash",
            name="uq_regression_suites_members_hash",
        ),
        Index("ix_regression_suites_suite_id", "suite_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    suite_id: Mapped[UUID] = mapped_column(Uuid)
    suite_version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    members_hash: Mapped[str] = mapped_column(String(64))
    members_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
