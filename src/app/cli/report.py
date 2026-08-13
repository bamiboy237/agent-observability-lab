"""This module defines the stable eight-scenario proof report.

The report records every scenario exactly once, whether it saved and ran or
failed, with its case version, bundle hash, source evidence, configuration
versions, and per-side run comparison. The same inputs produce the same
report content except the explicit generated-at timestamp.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.comparison.compare import RunComparison
from app.domain.evidence.schemas import TraceSourceRef
from app.domain.regression.schemas import CaseSourceType
from app.domain.suite.schemas import SuiteComparisonTotals, SuiteVerdict

PROOF_REPORT_SCHEMA_VERSION = "1.0.0"


class ProofScenarioStatus(StrEnum):
    """This enum classifies one scenario's place in the proof report."""

    SAVED_AND_RUN = "saved_and_run"
    FAILED = "failed"


class ProofScenarioResult(BaseModel):
    """This class stores one scenario's full proof trail or its failure."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    status: ProofScenarioStatus
    source_type: CaseSourceType | None = None
    case_id: UUID | None = None
    case_version: int | None = None
    bundle_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_ref: TraceSourceRef | None = None
    evidence_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    configuration_version: str | None = None
    comparison: RunComparison | None = None
    error: str | None = None


class ProofReport(BaseModel):
    """This class stores one complete eight-scenario proof report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=PROOF_REPORT_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    mode: str = Field(pattern=r"^(offline|hosted)$")
    generated_at: str = Field(min_length=1, max_length=100)
    suite_id: UUID
    suite_version: int = Field(ge=1)
    suite_name: str
    scenarios: tuple[ProofScenarioResult, ...] = Field(min_length=1)
    totals: SuiteComparisonTotals = Field(default_factory=SuiteComparisonTotals)
    verdict: SuiteVerdict = SuiteVerdict.INCONCLUSIVE
    verdict_reason: str = Field(min_length=1, max_length=2000)
