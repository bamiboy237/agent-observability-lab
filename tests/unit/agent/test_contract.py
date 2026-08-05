"""This module checks the typed contract for the agent.

This module checks the routing plan.
This module checks the settings for the model.
"""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.domain.agent.schemas import (
    AnswerContext,
    ReasonCode,
    RefundProposal,
    RouteIntent,
    RoutingDecision,
    SupportOutcome,
    SupportRequest,
    SupportResponse,
)
from app.domain.agent.service import plan_turn
from app.domain.support.schemas import OrderStatus


def make_routing(**overrides: Any) -> RoutingDecision:
    values: dict[str, Any] = {
        "intent": RouteIntent.ORDER_STATUS,
        "confidence": 0.9,
    }
    values.update(overrides)
    return RoutingDecision(**values)  # type: ignore[arg-type]


def test_valid_routing_decision_round_trips() -> None:
    decision = make_routing(intent=RouteIntent.POLICY, confidence=0.75)

    assert decision.intent is RouteIntent.POLICY
    assert decision.confidence == 0.75


@pytest.mark.parametrize("intent", ["billing", "order_status ", "", 42])
def test_invalid_route_intent_rejected(intent: object) -> None:
    with pytest.raises(ValidationError):
        make_routing(intent=intent)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0, -1.0])
def test_confidence_out_of_range_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_routing(confidence=confidence)


def test_request_requires_customer_and_message() -> None:
    with pytest.raises(ValidationError):
        SupportRequest(customer_id=uuid4(), message="")  # type: ignore[arg-type]

    request = SupportRequest(customer_id=uuid4(), message="Where is my order?")
    assert request.message == "Where is my order?"


def test_context_and_response_round_trip() -> None:
    customer_id = uuid4()
    routing = make_routing(intent=RouteIntent.REFUND, confidence=0.8)
    proposal = RefundProposal(
        proposal_id=uuid4(),
        order_id=uuid4(),
        customer_id=customer_id,
        amount=Decimal("48.25"),
        policy_version="2026-07-30",
    )
    context = AnswerContext(routing=routing, proposal=proposal)
    response = SupportResponse(
        intent=RouteIntent.REFUND,
        outcome=SupportOutcome.COMPLETED,
        reason_code=ReasonCode.REFUND_PROPOSED,
        message="We can refund your order.",
        context=context,
    )

    restored = SupportResponse.model_validate_json(response.model_dump_json())
    assert restored == response
    assert restored.context.proposal is not None


def test_plan_turn_answers_when_reference_present() -> None:
    plan = plan_turn(make_routing(intent=RouteIntent.ORDER_STATUS, order_id=uuid4()))
    assert plan.action == "answer"

    plan = plan_turn(make_routing(intent=RouteIntent.POLICY))
    assert plan.action == "answer"


def test_plan_turn_escalates_when_reference_missing() -> None:
    plan = plan_turn(make_routing(intent=RouteIntent.ORDER_STATUS))
    assert plan.action == "escalate"
    assert plan.reason_code is ReasonCode.ESCALATED_MISSING_REFERENCE

    plan = plan_turn(make_routing(intent=RouteIntent.REFUND))
    assert plan.action == "escalate"
    assert plan.reason_code is ReasonCode.REFUND_BLOCKED_MISSING_REFERENCE


def test_plan_turn_escalates_requested_intent() -> None:
    plan = plan_turn(make_routing(intent=RouteIntent.ESCALATE))
    assert plan.action == "escalate"
    assert plan.reason_code is ReasonCode.ESCALATED


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://user:password@localhost:5432/app",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_model_settings_require_provider_and_name_together() -> None:
    with pytest.raises(ValidationError, match="MODEL_PROVIDER and MODEL_NAME"):
        make_settings(model_provider="openai")
    with pytest.raises(ValidationError, match="MODEL_PROVIDER and MODEL_NAME"):
        make_settings(model_name="gpt-4o")


def test_model_settings_require_api_key_for_hosted_endpoints() -> None:
    with pytest.raises(ValidationError, match="MODEL_API_KEY"):
        make_settings(model_provider="openai", model_name="gpt-4o")


def test_model_settings_allow_keyless_local_endpoint() -> None:
    settings = make_settings(
        model_provider="openai",
        model_name="local-model",
        model_base_url="http://localhost:11434/v1",
    )
    assert settings.model_configured


def test_model_settings_accept_complete_configuration() -> None:
    settings = make_settings(
        model_provider="anthropic",
        model_name="claude-sonnet-4-6",
        model_api_key="sk-ant-test",
    )
    assert settings.model_configured
    assert "sk-ant-test" not in repr(settings)
    assert "sk-ant-test" not in settings.model_dump_json()


def test_langsmith_incomplete_settings_do_not_fail() -> None:
    settings = make_settings(langsmith_tracing=True)
    assert settings.langsmith_tracing is True
    assert settings.langsmith_api_key is None


def test_order_status_enum_contract() -> None:
    assert OrderStatus.DELIVERED.value == "delivered"
