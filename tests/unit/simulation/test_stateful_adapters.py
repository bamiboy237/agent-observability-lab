"""This module tests the disposable stateful support adapter for checkpoint 4.4.

Refund and ticket actions mutate only in-memory scenario state and report
before/after values with stable reason codes. Reset restores the exact
initial state. This fast unit-test substitute never touches PostgreSQL.
"""

import pytest

from app.domain.simulation.errors import (
    UnsupportedArgumentsError,
    UnsupportedStateError,
    UnsupportedToolError,
)
from app.domain.simulation.scenarios import DELIVERED_ORDER, SCENARIO_BY_ID
from app.domain.simulation.stateful import StatefulSupportAdapter
from app.domain.support.schemas import OrderStatus


def _scenario_state():
    return SCENARIO_BY_ID["phase2-05-unconfirmed-refund"].initial_state


async def test_calls_without_seed_fail_with_unsupported_state() -> None:
    adapter = StatefulSupportAdapter()
    with pytest.raises(UnsupportedStateError, match="no scenario state was seeded"):
        await adapter.call("get_order_status", {"order_id": DELIVERED_ORDER})


async def test_get_order_status_reads_disposable_state() -> None:
    adapter = StatefulSupportAdapter()
    await adapter.seed(_scenario_state())

    result = await adapter.call("get_order_status", {"order_id": DELIVERED_ORDER})

    assert result.ok is True
    assert result.payload["status"] == "delivered"
    assert result.payload["customer_id"] == str(_scenario_state().orders[0].customer_id)


async def test_missing_order_returns_order_not_found() -> None:
    adapter = StatefulSupportAdapter()
    await adapter.seed(_scenario_state())

    result = await adapter.call(
        "get_order_status",
        {"order_id": "00000000-0000-0000-0000-00000000dead"},
    )

    assert result.ok is False
    assert result.error_code == "order_not_found"


async def test_refund_flow_mutates_only_disposable_state() -> None:
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    await adapter.seed(_scenario_state())

    proposal = await adapter.call("propose_refund", {"order_id": DELIVERED_ORDER})
    assert proposal.ok is True
    assert proposal.payload["policy_version"] == "2026-07-30"

    refunded = await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})

    assert refunded.ok is True
    assert refunded.payload["status"] == "refunded"
    mutations = adapter.mutations()
    assert len(mutations) == 1
    mutation = mutations[0]
    assert mutation.resource == "order"
    assert mutation.resource_id == str(DELIVERED_ORDER)
    assert mutation.field == "status"
    assert mutation.before == "delivered"
    assert mutation.after == "refunded"
    assert mutation.reason_code == "refund_executed"


async def test_unconfirmed_refund_is_rejected_without_mutation() -> None:
    adapter = StatefulSupportAdapter(refund_confirmed=False)
    await adapter.seed(_scenario_state())

    await adapter.call("propose_refund", {"order_id": DELIVERED_ORDER})
    result = await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})

    assert result.ok is False
    assert result.error_code == "refund_not_confirmed"
    assert adapter.mutations() == ()


async def test_confirm_without_proposal_is_rejected() -> None:
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    await adapter.seed(_scenario_state())

    result = await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})

    assert result.ok is False
    assert result.error_code == "refund_not_confirmed"
    assert adapter.mutations() == ()


async def test_ineligible_status_is_rejected() -> None:
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    state = SCENARIO_BY_ID["phase2-03-database-timeout"].initial_state
    await adapter.seed(state)
    shipped = state.orders[0]
    assert shipped.status is OrderStatus.SHIPPED

    result = await adapter.call("propose_refund", {"order_id": shipped.id})

    assert result.ok is False
    assert result.error_code == "invalid_transition"
    assert adapter.mutations() == ()


async def test_escalation_creates_ticket_with_mutation() -> None:
    adapter = StatefulSupportAdapter()
    await adapter.seed(_scenario_state())

    result = await adapter.call("escalate", {"subject": "Escalated support request"})

    assert result.ok is True
    assert result.payload["subject"] == "Escalated support request"
    mutations = adapter.mutations()
    assert len(mutations) == 1
    assert mutations[0].resource == "ticket"
    assert mutations[0].field == "created"
    assert mutations[0].before is None
    assert mutations[0].reason_code == "ticket_created"
    assert mutations[0].after["status"] == "open"


async def test_seeded_state_stays_immutable_across_mutations() -> None:
    original_state = _scenario_state()
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    await adapter.seed(original_state)

    await adapter.call("propose_refund", {"order_id": DELIVERED_ORDER})
    await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})
    await adapter.call("escalate", {"subject": "Help"})

    assert original_state.orders[0].status is OrderStatus.DELIVERED
    assert original_state.tickets == ()


async def test_reset_restores_exact_initial_state() -> None:
    adapter = StatefulSupportAdapter(refund_confirmed=True)
    await adapter.seed(_scenario_state())

    await adapter.call("propose_refund", {"order_id": DELIVERED_ORDER})
    await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})
    await adapter.call("escalate", {"subject": "Help"})

    await adapter.reset()

    result = await adapter.call("get_order_status", {"order_id": DELIVERED_ORDER})
    assert result.payload["status"] == "delivered"
    assert adapter.mutations() == ()
    assert adapter.state_transitions() == (
        "order:delivered->refunded",
        "ticket:created",
    )

    repeat = await adapter.call("confirm_refund", {"order_id": DELIVERED_ORDER})
    assert repeat.error_code == "refund_not_confirmed"


async def test_unknown_tool_is_rejected() -> None:
    adapter = StatefulSupportAdapter()
    await adapter.seed(_scenario_state())

    with pytest.raises(UnsupportedToolError, match="does not offer tool"):
        await adapter.call("delete_order", {"order_id": DELIVERED_ORDER})


async def test_bad_arguments_are_rejected() -> None:
    adapter = StatefulSupportAdapter()
    await adapter.seed(_scenario_state())

    with pytest.raises(UnsupportedArgumentsError):
        await adapter.call("get_order_status", {"order_id": {"nested": True}})
    with pytest.raises(UnsupportedArgumentsError):
        await adapter.call("escalate", {"subject": ""})


def test_stateful_adapter_reports_kind_and_tools() -> None:
    adapter = StatefulSupportAdapter()
    assert adapter.kind == "stateful"
    assert adapter.supported_tools() == (
        "get_order_status",
        "get_policy",
        "propose_refund",
        "confirm_refund",
        "escalate",
    )
