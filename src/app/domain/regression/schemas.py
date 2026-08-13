"""This module defines the versioned regression case library schemas.

A regression case is the permanent, immutable record of one accepted
``SimulationBundle``. Every case has a stable case id derived from the
scenario and its source type, and an immutable case version that increases
when the bundle content changes. The read model surfaces the exact bundle,
its content hash, the source evidence links, and the configuration versions,
and validates that all stored provenance matches the bundle content.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.bundle.schemas import ConfigurationVersions, SimulationBundle
from app.domain.evidence.schemas import TraceSourceRef

REGRESSION_CASE_SCHEMA_VERSION = "1.0.0"


class CaseSourceType(StrEnum):
    """This enum limits why a source case entered the regression library."""

    INCIDENT = "incident"
    SUSPICIOUS_SUCCESS = "suspicious_success"
    DESIGNED_EDGE_CASE = "designed_edge_case"
    MODEL_COMPARISON = "model_comparison"


class CaseSaveStatus(StrEnum):
    """This enum classifies one save of an accepted bundle."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"


class CaseSaveResult(BaseModel):
    """This class reports the deterministic outcome of one case save."""

    model_config = ConfigDict(extra="forbid")

    status: CaseSaveStatus
    case_id: UUID
    case_version: int = Field(ge=1)
    bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CaseSummary(BaseModel):
    """This class stores the list view of one case with its latest version."""

    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    source_type: CaseSourceType
    scenario_id: str
    latest_version: int = Field(ge=1)
    latest_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str = Field(min_length=1, max_length=100)


class RegressionCase(BaseModel):
    """This class stores one exact immutable version of a saved case.

    Every provenance field at the case level must match the stored bundle:
    the bundle content hash, the source evidence link, the evidence content
    hash, the configuration versions, and the scenario id. A mismatch means
    the record is corrupt, so the schema rejects it.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=REGRESSION_CASE_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    case_id: UUID
    case_version: int = Field(ge=1)
    source_type: CaseSourceType
    scenario_id: str
    bundle: SimulationBundle
    bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ref: TraceSourceRef | None = None
    evidence_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    configuration_versions: ConfigurationVersions
    created_at: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_provenance(self) -> "RegressionCase":
        """This method rejects a case whose provenance does not match its bundle."""
        if self.bundle.content_hash is None or self.bundle_content_hash != self.bundle.content_hash:
            raise ValueError("case bundle hash must match the stored bundle content hash")
        if self.evidence_ref != self.bundle.evidence_ref:
            raise ValueError("case evidence link must match the stored bundle evidence link")
        if self.evidence_content_hash != self.bundle.evidence_content_hash:
            raise ValueError("case evidence hash must match the stored bundle evidence hash")
        if self.configuration_versions != self.bundle.configuration_versions:
            raise ValueError(
                "case configuration versions must match the stored bundle configuration versions"
            )
        if self.scenario_id != self.bundle.scenario.scenario_id:
            raise ValueError("case scenario id must match the stored bundle scenario id")
        return self
