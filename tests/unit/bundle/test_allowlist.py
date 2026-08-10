"""This module tests the allowlist redaction and rejection for checkpoint 5.2.

The compiler rejects unknown fields rather than silently copying them, and
the final bundle scanner rejects credentials, secrets, authorization headers,
unrestricted private text, and unexpected nested data.
"""

import pytest

from app.domain.bundle.allowlist import (
    FORBIDDEN_VALUE_PARTS,
    RESOURCE_ALLOWLIST,
    scan_bundle_content,
    validate_fixture_payload,
    validate_resource_seed,
)
from app.domain.bundle.errors import ForbiddenDataError


def test_resource_allowlist_has_expected_fields() -> None:
    assert RESOURCE_ALLOWLIST["order"] == frozenset({"id", "customer_id", "status", "total_amount"})
    assert RESOURCE_ALLOWLIST["policy"] == frozenset(
        {"id", "slug", "version", "title", "content", "content_hash"}
    )


def test_unknown_resource_type_is_rejected() -> None:
    with pytest.raises(ForbiddenDataError, match="unknown resource type"):
        validate_resource_seed("secret_store", {"id": "x"})


def test_resource_seed_rejects_unknown_field() -> None:
    with pytest.raises(ForbiddenDataError, match="non-allowlisted"):
        validate_resource_seed(
            "order",
            {"id": "x", "customer_id": "y", "status": "delivered", "secret": "z"},
        )


def test_resource_seed_rejects_credentials() -> None:
    with pytest.raises(ForbiddenDataError, match="sensitive key"):
        validate_resource_seed(
            "order",
            {"id": "x", "customer_id": "y", "status": "delivered", "api_key": "z"},
        )


def test_customer_seed_accepts_approved_synthetic_fields() -> None:
    validate_resource_seed(
        "customer",
        {
            "id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
            "name": "customer-abc",
            "email": "customer-abc@example.invalid",
        },
    )


def test_seed_record_rejects_nested_non_scalar_value() -> None:
    with pytest.raises(ForbiddenDataError, match="non-scalar"):
        validate_resource_seed(
            "order",
            {
                "id": "x",
                "customer_id": "y",
                "status": "delivered",
                "total_amount": {"secret": "1"},
            },
        )


def test_fixture_payload_rejects_forbidden_substring() -> None:
    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        validate_fixture_payload(
            "recorded_response",
            {"body": "the customer asked: what IS the refund policy?"},
            context="fixture",
            forbidden_substrings=("what is the refund policy",),
        )


def test_fixture_arguments_reject_sensitive_key() -> None:
    with pytest.raises(ForbiddenDataError, match="sensitive key"):
        scan_bundle_content(
            resources={},
            fixtures=[
                {
                    "type": "recorded_response",
                    "tool": "t",
                    "arguments": {"order_id": "x", "api_key": "sk-123"},
                    "payload": None,
                }
            ],
            forbidden_substrings=(),
        )


def test_scan_rejects_case_variant_forbidden_text() -> None:
    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        scan_bundle_content(
            resources={
                "policy": [
                    {
                        "id": "x",
                        "slug": "s",
                        "version": "v",
                        "title": "t",
                        "content": "the SECRET policy clause",
                        "content_hash": "h",
                    }
                ]
            },
            fixtures=[],
            forbidden_substrings=("secret",),
        )


def test_recorded_adapters_share_the_bundle_sensitive_key_list() -> None:
    from app.domain.simulation.errors import InvalidSimulationFixture
    from app.domain.simulation.recorded import sanitize_captured_data

    with pytest.raises(InvalidSimulationFixture):
        sanitize_captured_data(
            {"get_order_status": {'{"order_id":"x"}': {"payload": {"auth_header": "Bearer y"}}}},
            supported_tools=("get_order_status",),
        )


def test_fixture_payload_rejects_nested_secret_key() -> None:
    with pytest.raises(ForbiddenDataError, match="sensitive key"):
        validate_fixture_payload(
            "recorded_response",
            {"order": {"id": "1", "authorization": "Bearer x"}},
            context="fixture",
        )


def test_fixture_payload_rejects_private_text_key() -> None:
    with pytest.raises(ForbiddenDataError, match="sensitive key"):
        validate_fixture_payload(
            "recorded_response",
            {"order": {"id": "1", "message": "unrestricted customer text"}},
            context="fixture",
        )


def test_fixture_payload_rejects_non_json_data() -> None:
    with pytest.raises(ForbiddenDataError, match="non-JSON"):
        validate_fixture_payload("recorded_response", object(), context="fixture")


def test_fixture_payload_accepts_nested_lists() -> None:
    validate_fixture_payload(
        "recorded_response",
        [{"id": "1", "status": "delivered"}, ["a", 1, None]],
        context="fixture",
    )


def test_scan_rejects_forbidden_private_text() -> None:
    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        scan_bundle_content(
            resources={
                "policy": [
                    {
                        "id": "x",
                        "slug": "s",
                        "version": "v",
                        "title": "t",
                        "content": "secret",
                        "content_hash": "h",
                    }
                ]
            },
            fixtures=[],
            forbidden_substrings=("secret",),
        )


def test_scan_rejects_forbidden_value_part() -> None:
    assert any("sk-" in part for part in FORBIDDEN_VALUE_PARTS)
    with pytest.raises(ForbiddenDataError, match="forbidden value"):
        scan_bundle_content(
            resources={
                "order": [
                    {
                        "id": "e5afa83a-25c7-5b71-98bb-b8eae0d188c0",
                        "customer_id": "e693cb4c-98a7-5d3d-bd7a-1c0c554ab528",
                        "status": "delivered",
                        "total_amount": "1",
                    }
                ]
            },
            fixtures=[
                {"type": "recorded_response", "tool": "t", "arguments": {}, "payload": "sk-abc123"}
            ],
            forbidden_substrings=(),
        )
