"""This module defines the application service for the regression case library."""

from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from app.domain.bundle.schemas import ReviewStatus, SimulationBundle, compute_bundle_hash
from app.domain.regression.errors import (
    CaseNotFoundError,
    InvalidCaseBundleError,
    ReviewRequiredError,
)
from app.domain.regression.repository import RegressionCaseRepository, StoredCase
from app.domain.regression.schemas import (
    CaseSaveResult,
    CaseSaveStatus,
    CaseSourceType,
    CaseSummary,
    RegressionCase,
)

REGRESSION_CASE_NAMESPACE = UUID("9c4f1d6a-3b8e-4a7f-9c2d-5e1b7a0f6d34")


def stable_case_id(scenario_id: str, source_type: CaseSourceType) -> UUID:
    """This function returns the stable case id for one scenario and source type.

    The same scenario and source type always map to the same case id, so
    changed bundle content becomes a new immutable version of the same case
    instead of a new case. A different source type for the same scenario is
    a different case.
    """
    return uuid5(REGRESSION_CASE_NAMESPACE, f"{scenario_id}|{source_type.value}")


class RegressionCaseService:
    """This class connects callers to the immutable case persistence boundary."""

    def __init__(self, repository: RegressionCaseRepository) -> None:
        self._repository = repository

    async def save_case(
        self,
        *,
        bundle: SimulationBundle,
        source_type: CaseSourceType,
    ) -> CaseSaveResult:
        """This method saves one accepted bundle as a deterministic case version.

        Saving the same bundle again returns the existing version unchanged.
        Saving changed content creates the next immutable version without
        touching history. A bundle without an approved review, or whose
        content hash does not match its content, is rejected.
        """
        if bundle.review.status is not ReviewStatus.APPROVED:
            raise ReviewRequiredError(
                scenario_id=bundle.scenario.scenario_id,
                state=bundle.review.status.value,
            )
        computed_hash = compute_bundle_hash(bundle)
        if bundle.content_hash is None or bundle.content_hash != computed_hash:
            raise InvalidCaseBundleError(detail="content hash does not match the bundle content")

        case_id = stable_case_id(bundle.scenario.scenario_id, source_type)
        latest = await self._repository.latest_case(case_id)
        if latest is not None and latest.bundle_content_hash == bundle.content_hash:
            return CaseSaveResult(
                status=CaseSaveStatus.UNCHANGED,
                case_id=case_id,
                case_version=latest.case_version,
                bundle_content_hash=latest.bundle_content_hash,
            )

        case_version = latest.case_version + 1 if latest is not None else 1
        evidence_ref = bundle.evidence_ref
        stored_case = StoredCase(
            id=uuid4(),
            case_id=case_id,
            case_version=case_version,
            source_type=source_type.value,
            scenario_id=bundle.scenario.scenario_id,
            bundle_content_hash=bundle.content_hash,
            source_platform=evidence_ref.platform if evidence_ref is not None else None,
            source_trace_id=evidence_ref.trace_id if evidence_ref is not None else None,
            source_url=evidence_ref.url if evidence_ref is not None else None,
            evidence_content_hash=bundle.evidence_content_hash,
            configuration_version=bundle.configuration_versions.configuration_version,
            bundle_json=bundle.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
        saved = await self._repository.insert_version(stored_case)
        if saved is None:
            latest = await self._repository.latest_case(case_id)
            if latest is None:
                raise CaseNotFoundError(case_id=case_id, case_version=None)
            status = (
                CaseSaveStatus.UNCHANGED
                if latest.bundle_content_hash == bundle.content_hash
                else CaseSaveStatus.UPDATED
            )
            return CaseSaveResult(
                status=status,
                case_id=case_id,
                case_version=latest.case_version,
                bundle_content_hash=latest.bundle_content_hash,
            )
        status = CaseSaveStatus.UPDATED if latest is not None else CaseSaveStatus.CREATED
        return CaseSaveResult(
            status=status,
            case_id=case_id,
            case_version=case_version,
            bundle_content_hash=bundle.content_hash,
        )

    async def list_cases(self) -> tuple[CaseSummary, ...]:
        """This method returns one summary per case with its latest version."""
        rows = await self._repository.list_latest_cases()
        return tuple(
            CaseSummary(
                case_id=row.case_id,
                source_type=CaseSourceType(row.source_type),
                scenario_id=row.scenario_id,
                latest_version=row.case_version,
                latest_content_hash=row.bundle_content_hash,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        )

    async def get_case(self, *, case_id: UUID, case_version: int) -> RegressionCase:
        """This method returns one exact immutable version of one case.

        The stored bundle is re-validated on retrieval, so a stored case can
        never return an unapproved or tampered bundle.
        """
        row = await self._repository.case_version(case_id, case_version)
        if row is None:
            raise CaseNotFoundError(case_id=case_id, case_version=case_version)
        bundle = SimulationBundle.model_validate(row.bundle_json)
        return RegressionCase(
            case_id=row.case_id,
            case_version=row.case_version,
            source_type=CaseSourceType(row.source_type),
            scenario_id=row.scenario_id,
            bundle=bundle,
            bundle_content_hash=row.bundle_content_hash,
            evidence_ref=bundle.evidence_ref,
            evidence_content_hash=bundle.evidence_content_hash,
            configuration_versions=bundle.configuration_versions,
            created_at=row.created_at.isoformat(),
        )
