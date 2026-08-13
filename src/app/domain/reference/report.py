"""This module defines the Phase 7.6 reference-workflow integration report.

The report records, for every approved workflow, the measured setup time,
the reused and integration-only code, the custom adapters, the missing
capabilities and unsupported behavior, the cleanup result, the verification
evidence, and how the scenario, tools, state, controls, and success measures
reflect a real operating team.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reference.compare import ReferenceComparison
from app.domain.reference.runner import ReferenceRun

REFERENCE_REPORT_SCHEMA_VERSION = "2.0.0"


class WorkflowEntry(BaseModel):
    """This class stores one workflow's bounded integration evidence."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    name: str
    source: str
    stateful: bool = True
    safe_tools: int = 0
    sensitive_tools: int = 0
    gate_required: bool = False
    run_duration_seconds: float = 0.0
    setup_effort_notes: str | None = Field(default=None, max_length=1000)
    baseline: ReferenceRun
    candidate: ReferenceRun
    comparison: ReferenceComparison
    reused_code: tuple[str, ...] = ()
    integration_code_lines: int = 0
    custom_adapters: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    unsupported_behavior: tuple[str, ...] = ()
    real_operation_notes: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()


class ReferenceWorkflowReport(BaseModel):
    """This class stores one complete Phase 7.6 report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=REFERENCE_REPORT_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    generated_at: str = Field(min_length=1, max_length=100)
    workflows: tuple[WorkflowEntry, ...] = ()
    total_run_duration_seconds: float = 0.0
    flagged_contract_changes: tuple[str, ...] = ()
