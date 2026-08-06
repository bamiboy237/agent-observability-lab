"""This module defines models that store imported trace evidence."""

from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.evidence.schemas import TraceSourceRef

EVIDENCE_NAMESPACE = UUID("2f1d4e9a-7c3b-4a5e-9d6f-1b2c3d4e5f60")


def stable_evidence_id(source: TraceSourceRef) -> UUID:
    """This function returns the stable evidence id for one source trace.

    The same source trace always maps to the same evidence id.
    Changed imports of that trace keep the id and raise the import version.
    """
    return uuid5(EVIDENCE_NAMESPACE, f"{source.platform}|{source.project or ''}|{source.trace_id}")


class TraceImport(Base):
    __tablename__ = "trace_imports"
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "content_hash",
            name="uq_trace_imports_evidence_hash",
        ),
        UniqueConstraint(
            "evidence_id",
            "import_version",
            name="uq_trace_imports_evidence_version",
        ),
        Index("ix_trace_imports_evidence_id", "evidence_id"),
        Index(
            "ix_trace_imports_source",
            "source_platform",
            "source_project",
            "source_trace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    evidence_id: Mapped[UUID] = mapped_column(Uuid)
    import_version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(20))
    source_platform: Mapped[str] = mapped_column(String(50))
    source_project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_trace_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    workflow_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
