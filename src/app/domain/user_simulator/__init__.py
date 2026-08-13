"""Hosted-model user simulation with allowlisted run artifacts.

The package root stays import-light: the generic event/flow/CLI layer loads
without touching the built-in support/reference adapters. ``ALL_PERSONAS``
and ``PERSONA_BY_ID`` are resolved lazily for callers that still use them.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ALL_PERSONAS", "PERSONA_BY_ID"]


def __getattr__(name: str) -> Any:
    if name == "ALL_PERSONAS":
        from app.domain.user_simulator.personas import ALL_PERSONAS

        return ALL_PERSONAS
    if name == "PERSONA_BY_ID":
        from app.domain.user_simulator.personas import PERSONA_BY_ID

        return PERSONA_BY_ID
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
