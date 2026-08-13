"""Failure analysis contracts.

The failure domain turns canonical :class:`TraceEvidence` into explainable
candidate labels.  It deliberately keeps the first grouping baseline small and
deterministic so reviewers can inspect every decision.
"""

from app.domain.failures.schemas import ConfirmedFailureGroup, FailureCandidate, FailureKind
from app.domain.failures.service import FailureReviewService

__all__ = [
    "ConfirmedFailureGroup",
    "FailureCandidate",
    "FailureKind",
    "FailureReviewService",
]
