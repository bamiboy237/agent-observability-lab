"""Feedback parsing and idempotent annotation persistence."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.evidence.schemas import TraceEvidence
from app.domain.failures.models import FeedbackAnnotationRecord
from app.domain.failures.schemas import (
    FeedbackAnnotation,
    FeedbackImportResult,
    FeedbackImportStatus,
    content_hash,
)


class FeedbackError(ValueError):
    """Base error for annotation validation and import."""


class MalformedFeedback(FeedbackError):
    """The required annotation fields are not usable."""


class UnknownFeedbackReference(FeedbackError):
    """An annotation points at a trace or event outside the selected evidence."""


def parse_langsmith_annotation(
    raw: Mapping[str, object],
    *,
    platform: str = "langsmith",
    project: str | None = None,
) -> FeedbackAnnotation:
    """Map one LangSmith-style annotation without copying trace facts.

    Optional score, comment, reviewer, and timestamp fields are treated as
    absent when providers send malformed values. Required identity and label
    fields fail closed.
    """
    annotation_id = raw.get("id") or raw.get("annotation_id")
    trace_id = raw.get("trace_id") or raw.get("run_id")
    label = raw.get("label") or raw.get("value") or raw.get("key")
    if not isinstance(annotation_id, str) or not annotation_id:
        raise MalformedFeedback("annotation id is required")
    if not isinstance(trace_id, str) or not trace_id:
        raise MalformedFeedback("trace_id or run_id is required")
    if not isinstance(label, str) or not label:
        raise MalformedFeedback("annotation label is required")
    score_raw = raw.get("score")
    score = (
        float(score_raw)
        if isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool)
        else None
    )
    comment = raw.get("comment")
    reviewer = raw.get("user_id") or raw.get("reviewer")
    event_id = raw.get("event_id")
    created = raw.get("created_at") or raw.get("annotated_at")
    annotated_at = datetime(1970, 1, 1, tzinfo=UTC)
    if isinstance(created, str):
        try:
            annotated_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if annotated_at.tzinfo is None:
                annotated_at = annotated_at.replace(tzinfo=UTC)
        except ValueError:
            pass
    event_id_value = event_id if isinstance(event_id, str) else None
    comment_value = comment if isinstance(comment, str) else None
    reviewer_value = reviewer if isinstance(reviewer, str) else None
    source_url_value: str | None = None
    raw_url = raw.get("url")
    if isinstance(raw_url, str):
        source_url_value = raw_url
    correction_of_value: str | None = None
    raw_correction = raw.get("correction_of")
    if isinstance(raw_correction, str):
        correction_of_value = raw_correction
    payload = {
        "annotation_id": annotation_id,
        "source_platform": platform,
        "source_project": project,
        "trace_id": trace_id,
        "event_id": event_id_value,
        "label": label,
        "score": score,
        "comment": comment_value,
        "reviewer": reviewer_value,
        "annotated_at": annotated_at.isoformat(),
        "source_url": source_url_value,
        "correction_of": correction_of_value,
    }
    return FeedbackAnnotation(
        annotation_id=annotation_id,
        source_platform=platform,
        source_project=project,
        trace_id=trace_id,
        event_id=event_id_value,
        label=label,
        score=score,
        comment=comment_value,
        reviewer=reviewer_value,
        annotated_at=annotated_at,
        source_url=source_url_value,
        correction_of=correction_of_value,
        content_hash=content_hash(payload),
    )


class FeedbackStore(Protocol):
    """Persistence operations required by the feedback import service."""

    async def lock_annotation(self, annotation_id: str) -> None: ...

    async def find_exact_annotation(
        self,
        *,
        annotation_id: str,
        content_hash: str,
    ) -> FeedbackAnnotation | None: ...

    async def latest_revision(self, annotation_id: str) -> int: ...

    async def save_annotation(self, annotation: FeedbackAnnotation) -> bool: ...


class FeedbackImportService:
    """Import feedback revisions without mutating canonical trace evidence."""

    def __init__(self, store: FeedbackStore) -> None:
        self._store = store

    async def import_annotation(
        self,
        raw: Mapping[str, object],
        evidence: TraceEvidence,
        *,
        platform: str = "langsmith",
        project: str | None = None,
    ) -> FeedbackImportResult:
        annotation = parse_langsmith_annotation(raw, platform=platform, project=project)
        if annotation.trace_id != evidence.source.trace_id:
            raise UnknownFeedbackReference(
                f"annotation {annotation.annotation_id!r} references unknown trace "
                f"{annotation.trace_id!r}"
            )
        if annotation.event_id is not None and not any(
            event.event_id == annotation.event_id for event in evidence.events
        ):
            raise UnknownFeedbackReference(
                f"annotation {annotation.annotation_id!r} references unknown event "
                f"{annotation.event_id!r}"
            )
        await self._store.lock_annotation(annotation.annotation_id)
        existing = await self._store.find_exact_annotation(
            annotation_id=annotation.annotation_id,
            content_hash=annotation.content_hash,
        )
        if existing is not None:
            return FeedbackImportResult(
                status=FeedbackImportStatus.UNCHANGED,
                annotation_id=existing.annotation_id,
                revision=existing.revision,
                content_hash=existing.content_hash,
            )
        revision = await self._store.latest_revision(annotation.annotation_id) + 1
        stored = annotation.model_copy(update={"revision": revision})
        if not await self._store.save_annotation(stored):
            raced = await self._store.find_exact_annotation(
                annotation_id=annotation.annotation_id,
                content_hash=annotation.content_hash,
            )
            if raced is not None:
                return FeedbackImportResult(
                    status=FeedbackImportStatus.UNCHANGED,
                    annotation_id=raced.annotation_id,
                    revision=raced.revision,
                    content_hash=raced.content_hash,
                )
            raise FeedbackError("annotation revision conflicted; retry the import")
        return FeedbackImportResult(
            status=(
                FeedbackImportStatus.CREATED if revision == 1 else FeedbackImportStatus.CORRECTED
            ),
            annotation_id=stored.annotation_id,
            revision=revision,
            content_hash=stored.content_hash,
        )


class InMemoryFeedbackStore:
    """Small deterministic fake for unit tests and offline review."""

    def __init__(self) -> None:
        self.rows: list[FeedbackAnnotation] = []

    async def lock_annotation(self, annotation_id: str) -> None:
        return None

    async def find_exact_annotation(
        self,
        *,
        annotation_id: str,
        content_hash: str,
    ) -> FeedbackAnnotation | None:
        return next(
            (
                item
                for item in self.rows
                if item.annotation_id == annotation_id and item.content_hash == content_hash
            ),
            None,
        )

    async def latest_revision(self, annotation_id: str) -> int:
        return max(
            (item.revision for item in self.rows if item.annotation_id == annotation_id),
            default=0,
        )

    async def save_annotation(self, annotation: FeedbackAnnotation) -> bool:
        if any(
            item.annotation_id == annotation.annotation_id and item.revision == annotation.revision
            for item in self.rows
        ):
            return False
        self.rows.append(annotation)
        return True


class SqlAlchemyFeedbackStore:
    """PostgreSQL feedback persistence with advisory import locks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_annotation(self, annotation_id: str) -> None:
        lock_key = int.from_bytes(annotation_id.encode()[:8].ljust(8, b"\0"), "big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    @staticmethod
    def _to_schema(row: FeedbackAnnotationRecord) -> FeedbackAnnotation:
        return FeedbackAnnotation.model_validate(row.annotation_json)

    async def find_exact_annotation(
        self,
        *,
        annotation_id: str,
        content_hash: str,
    ) -> FeedbackAnnotation | None:
        statement = select(FeedbackAnnotationRecord).where(
            FeedbackAnnotationRecord.annotation_id == annotation_id,
            FeedbackAnnotationRecord.content_hash == content_hash,
        )
        row = await self._session.scalar(statement)
        return self._to_schema(row) if row is not None else None

    async def latest_revision(self, annotation_id: str) -> int:
        statement = select(func.max(FeedbackAnnotationRecord.revision)).where(
            FeedbackAnnotationRecord.annotation_id == annotation_id
        )
        return int(await self._session.scalar(statement) or 0)

    async def save_annotation(self, annotation: FeedbackAnnotation) -> bool:
        row = FeedbackAnnotationRecord(
            id=uuid4(),
            annotation_id=annotation.annotation_id,
            revision=annotation.revision,
            content_hash=annotation.content_hash,
            source_platform=annotation.source_platform,
            source_project=annotation.source_project,
            trace_id=annotation.trace_id,
            event_id=annotation.event_id,
            annotation_json=annotation.model_dump(mode="json"),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            return False
        return True


__all__ = [
    "FeedbackError",
    "FeedbackImportService",
    "InMemoryFeedbackStore",
    "MalformedFeedback",
    "SqlAlchemyFeedbackStore",
    "UnknownFeedbackReference",
    "parse_langsmith_annotation",
]
