"""This module tests recorded-read adapters for checkpoint 4.3.

Recorded reads match by tool name and normalized arguments. Unexpected
access fails closed. Scripted entries reproduce timeout and malformed
tool-response cases without any network access.
"""

import pytest

from app.domain.simulation.adapters import normalize_arguments
from app.domain.simulation.errors import (
    InvalidSimulationFixture,
    UnsupportedArgumentsError,
    UnsupportedToolError,
)
from app.domain.simulation.recorded import (
    RecordedClock,
    RecordedOrderLookup,
    RecordedPolicyRetrieval,
    RecordedProviderResponse,
)
from app.domain.simulation.scenarios import DELIVERED_ORDER, SHIPPED_ORDER


def _order_table() -> dict[str, object]:
    return {
        "get_order_status": {
            normalize_arguments({"order_id": SHIPPED_ORDER}): [
                {"error_code": "timeout"},
                {
                    "payload": {
                        "id": str(SHIPPED_ORDER),
                        "status": "shipped",
                        "total_amount": "135.00",
                    }
                },
            ],
            normalize_arguments({"order_id": DELIVERED_ORDER}): {
                "payload": {
                    "id": str(DELIVERED_ORDER),
                    "status": "delivered",
                    "total_amount": "48.25",
                }
            },
        }
    }


async def test_recorded_order_lookup_matches_normalized_arguments() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    result = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})
    assert result.ok is False
    assert result.error_code == "timeout"

    second = await adapter.call("get_order_status", {"order_id": str(SHIPPED_ORDER)})
    assert second.ok is True
    assert second.payload["status"] == "shipped"


async def test_recorded_lookup_replays_script_in_order() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    first = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})
    second = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})
    third = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})

    assert first.error_code == "timeout"
    assert second.ok is True
    assert third.ok is True
    assert third.payload == second.payload


async def test_reset_restarts_every_script() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})
    await adapter.reset()
    result = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})

    assert result.ok is False
    assert result.error_code == "timeout"


async def test_unexpected_arguments_fail_closed() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    with pytest.raises(UnsupportedArgumentsError, match="no recorded response"):
        await adapter.call("get_order_status", {"order_id": "00000000-0000-0000-0000-00000000dead"})

    with pytest.raises(UnsupportedArgumentsError):
        await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER, "mode": "verbose"})


async def test_unknown_tool_is_rejected() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    with pytest.raises(UnsupportedToolError, match="does not offer tool"):
        await adapter.call("get_order_status_v2", {"order_id": SHIPPED_ORDER})


async def test_recorded_policy_retrieval_serves_stale_policy() -> None:
    adapter = RecordedPolicyRetrieval()
    await adapter.sanitize(
        {
            "get_policy": {
                normalize_arguments({"slug": "refund-and-delivery"}): {
                    "payload": {
                        "version": "2025-01-01",
                        "title": "Refund and Delivery Policy",
                        "content": "Any order may be refunded at any time.",
                    }
                }
            }
        }
    )

    result = await adapter.call("get_policy", {"slug": "refund-and-delivery"})

    assert result.ok is True
    assert result.payload["version"] == "2025-01-01"


async def test_recorded_clock_returns_fixed_value() -> None:
    adapter = RecordedClock()
    await adapter.sanitize(
        {"clock.now": {normalize_arguments({}): {"payload": "2026-08-06T12:00:00Z"}}}
    )

    result = await adapter.call("clock.now", {})

    assert result.ok is True
    assert result.payload == "2026-08-06T12:00:00Z"


async def test_recorded_provider_response_replays_without_network() -> None:
    adapter = RecordedProviderResponse(
        dependency="payment.provider",
        tools=("check_refund_status",),
    )
    await adapter.sanitize(
        {
            "check_refund_status": {
                normalize_arguments({"refund_id": "refund-42"}): {
                    "payload": {"status": "settled", "settled_at": "2026-08-06T09:00:00Z"}
                }
            }
        }
    )

    result = await adapter.call("check_refund_status", {"refund_id": "refund-42"})

    assert result.ok is True
    assert result.payload["status"] == "settled"


async def test_malformed_response_returns_stable_error() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(
        {
            "get_order_status": {
                normalize_arguments({"order_id": SHIPPED_ORDER}): {"malformed": True}
            }
        }
    )

    result = await adapter.call("get_order_status", {"order_id": SHIPPED_ORDER})

    assert result.ok is False
    assert result.error_code == "malformed_response"


async def test_sanitize_rejects_unknown_tool() -> None:
    adapter = RecordedOrderLookup()
    with pytest.raises(InvalidSimulationFixture, match="not offered"):
        await adapter.sanitize(
            {
                "get_order_status": {
                    normalize_arguments({"order_id": SHIPPED_ORDER}): {"payload": {}}
                },
                "get_credit_card": {normalize_arguments({}): {"payload": {}}},
            }
        )


async def test_sanitize_rejects_sensitive_payload_keys() -> None:
    adapter = RecordedOrderLookup()
    with pytest.raises(InvalidSimulationFixture, match="sensitive"):
        await adapter.sanitize(
            {
                "get_order_status": {
                    normalize_arguments({"order_id": SHIPPED_ORDER}): {
                        "payload": {"api_key": "sk-live-secret"}
                    }
                }
            }
        )


async def test_sanitize_rejects_non_object_arguments_key() -> None:
    adapter = RecordedOrderLookup()
    with pytest.raises(InvalidSimulationFixture, match="non-object arguments key"):
        await adapter.sanitize({"get_order_status": {"[1, 2]": {"payload": {}}}})


async def test_non_normalizable_arguments_fail_closed() -> None:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(_order_table())

    with pytest.raises(UnsupportedArgumentsError):
        await adapter.call("get_order_status", {"order_id": {"nested": "value"}})


def test_recorded_adapters_report_no_transitions_and_no_mutations() -> None:
    adapter = RecordedOrderLookup()
    assert adapter.kind == "recorded"
    assert adapter.state_transitions() == ()
    assert adapter.mutations() == ()
    assert adapter.supported_tools() == ("get_order_status",)
