"""This module defines the versioned regression suite schemas.

A suite names an explicit set of exact immutable case versions. The suite
itself is versioned with the same deterministic rules as the case library:
saving the same members returns the existing version unchanged, and changed
members create a visible new version without overwriting history. The
comparison result models keep every case result linked to its case version,
bundle hash, source evidence, and configuration.
"""

import json
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.comparison.compare import RunComparison
from app.domain.comparison.experiment import ConfigurationChangeType
from app.domain.evidence.schemas import TraceSourceRef

SUITE_SCHEMA_VERSION = "1.0.0"


class SuiteMemberRef(BaseModel):
    """This class names one exact immutable case version in a suite."""

    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    case_version: int = Field(ge=1)


class SuiteSaveStatus(StrEnum):
    """This enum classifies one save of a suite member set."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"


class SuiteSaveResult(BaseModel):
    """This class reports the deterministic outcome of one suite save."""

    model_config = ConfigDict(extra="forbid")

    status: SuiteSaveStatus
    suite_id: UUID
    suite_version: int = Field(ge=1)


class CaseSuite(BaseModel):
    """This class stores one exact immutable version of a case suite."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=SUITE_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    suite_id: UUID
    suite_version: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    members: tuple[SuiteMemberRef, ...] = Field(min_length=1)
    created_at: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_members(self) -> "CaseSuite":
        """This method rejects duplicate members in one suite version."""
        seen: set[tuple[UUID, int]] = set()
        for member in self.members:
            key = (member.case_id, member.case_version)
            if key in seen:
                raise ValueError(
                    f"duplicate suite member {member.case_id!r} v{member.case_version}"
                )
            seen.add(key)
        return self


class SuiteSummary(BaseModel):
    """This class stores the list view of one suite with its latest version."""

    model_config = ConfigDict(extra="forbid")

    suite_id: UUID
    name: str
    latest_version: int = Field(ge=1)
    member_count: int = Field(ge=1)
    created_at: str = Field(min_length=1, max_length=100)


def suite_members_hash(members: tuple[SuiteMemberRef, ...]) -> str:
    """This function returns the stable content hash of one ordered member set.

    The hash is order-independent and case-version-exact, so the same set of
    exact case versions always maps to the same suite content.
    """
    canonical = json.dumps(
        sorted(
            ({"case_id": str(member.case_id), "case_version": member.case_version}
             for member in members),
            key=lambda item: (item["case_id"], item["case_version"]),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


class SuiteSideTotals(BaseModel):
    """This class stores one side's cohort totals for a suite comparison."""

    model_config = ConfigDict(extra="forbid")

    success_count: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_retries: int = 0


class SuiteComparisonTotals(BaseModel):
    """This class stores the cohort totals of one suite comparison."""

    model_config = ConfigDict(extra="forbid")

    cases: int = 0
    comparable: int = 0
    candidate_passes: int = 0
    candidate_regresses: int = 0
    no_material_difference: int = 0
    insufficient_evidence: int = 0
    safety_regressions: int = 0
    missing_measurement_cases: int = 0
    coverage_failure_cases: int = 0
    baseline: SuiteSideTotals = Field(default_factory=SuiteSideTotals)
    candidate: SuiteSideTotals = Field(default_factory=SuiteSideTotals)


class SuiteVerdict(StrEnum):
    """This enum defines the cohort-level recommendation of one suite comparison."""

    RECOMMEND_CANDIDATE = "recommend_candidate"
    KEEP_BASELINE = "keep_baseline"
    INCONCLUSIVE = "inconclusive"


class SuiteCaseResult(BaseModel):
    """This class stores one suite member's baseline/candidate comparison."""

    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    case_version: int = Field(ge=1)
    scenario_id: str
    bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ref: TraceSourceRef | None = None
    evidence_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    comparison: RunComparison


class SuiteComparisonResult(BaseModel):
    """This class stores one complete baseline/candidate suite comparison.

    Every case result carries its exact case version, bundle hash, source
    evidence link, and both normalized runs. The verdict is deterministic:
    any regression keeps the baseline, any incomplete evidence makes the
    result inconclusive, and only then does task success decide.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=SUITE_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    suite_id: UUID
    suite_version: int = Field(ge=1)
    suite_name: str
    change_type: ConfigurationChangeType
    baseline_label: str
    candidate_label: str
    cases: tuple[SuiteCaseResult, ...] = ()
    totals: SuiteComparisonTotals = Field(default_factory=SuiteComparisonTotals)
    verdict: SuiteVerdict = SuiteVerdict.INCONCLUSIVE
    verdict_reason: str = Field(min_length=1, max_length=2000)
