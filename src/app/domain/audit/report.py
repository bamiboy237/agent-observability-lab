"""This module defines the stable Phase 7 audit report.

The report separates observed facts, flagged findings, fixed defects,
remaining risks, and checks that could not run, so a reviewer can see
exactly what the audit proved and what it did not.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.audit.scanner import ScanFinding

AUDIT_REPORT_SCHEMA_VERSION = "1.0.0"


class AuditReport(BaseModel):
    """This class stores one complete privacy, isolation, and reproducibility audit."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=AUDIT_REPORT_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    environment: str
    generated_at: str = Field(min_length=1, max_length=100)
    scanned_bundles: int = 0
    scanned_artifacts: int = 0
    findings: tuple[ScanFinding, ...] = ()
    facts: tuple[str, ...] = ()
    fixed_defects: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    skipped_checks: tuple[str, ...] = ()
