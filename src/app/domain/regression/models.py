"""This module defines the model that stores immutable regression case versions."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CASE_SOURCE_TYPES = (
    "incident",
    "suspicious_success",
    "designed_edge_case",
    "model_comparison",
)


class RegressionCaseRecord(Base):
    """This class stores one immutable version of one regression case.

    The case id is stable for one scenario and source type; the case version
    increases whenever the bundle content changes. History is never
    overwritten: each content hash is stored at most once per case.
    """

    __tablename__ = "regression_cases"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN {CASE_SOURCE_TYPES}",
            name="ck_regression_cases_source_type",
        ),
        UniqueConstraint(
            "case_id",
            "case_version",
            name="uq_regression_cases_case_version",
        ),
        UniqueConstraint(
            "case_id",
            "bundle_content_hash",
            name="uq_regression_cases_case_hash",
        ),
        Index("ix_regression_cases_case_id", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(Uuid)
    case_version: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(30))
    scenario_id: Mapped[str] = mapped_column(String(100))
    bundle_content_hash: Mapped[str] = mapped_column(String(64))
    source_platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_trace_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    evidence_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    configuration_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bundle_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
