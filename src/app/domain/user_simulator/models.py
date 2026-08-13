"""Safe schemas for simulator model boundaries and final reports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    goal_reached: bool = False
    confirmation_action: Literal["confirm_refund", "approve_sensitive_action"] | None = None


class BusinessChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str | None = None
    arguments: dict[str, object] = Field(default_factory=dict)
    message: str = Field(min_length=1, max_length=4000)
    end: bool = False


class SimulatorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    run_id: str
    case_id: str
    kind: str
    model_provider: str
    model_name: str
    end_reason: str
    turns: int = Field(ge=0)
    verified_goal: bool
    evidence: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    total_tokens: int = Field(default=0, ge=0)
    total_latency_ms: float = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
