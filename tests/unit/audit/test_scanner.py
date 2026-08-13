"""This module tests the audit scanner for checkpoint 7.7.

The scanner flags known secret formats, forbidden field names, and email
addresses in saved bundles and generated reports, and leaves clean synthetic
payloads untouched.
"""

from app.domain.audit.scanner import FORBIDDEN_KEYS, scan_json_text, scan_payload


def test_scanner_flags_secret_formats() -> None:
    payload = {
        "bundle": {
            "scenario": {"request": {"message": "call me sk-ant-abcdefghijklmnopqrstuvwxyz123"}},
            "review": {"reason": "password=hunter2hunter2hunter2"},
        }
    }
    findings = scan_payload(payload, context="test")

    kinds = {finding.kind for finding in findings}
    assert "anthropic_api_key" in kinds
    assert "generic_password" in kinds
    assert all(finding.context == "test" for finding in findings)


def test_scanner_flags_forbidden_keys_and_emails() -> None:
    payload = {
        "api_key": "super-secret-value",
        "customer": {"email": "real.person@private-corp.com"},
        "ok": "fine",
    }
    findings = scan_payload(payload, context="test")

    kinds = {finding.kind for finding in findings}
    assert "forbidden_key:api_key" in kinds
    assert "email" in kinds


def test_scanner_leaves_clean_synthetic_payload_untouched() -> None:
    payload = {
        "bundle_id": "a561f87b-d946-5337-9524-d8e2c21c46ae",
        "content_hash": "4f9b756a0837135c" + "0" * 48,
        "scenario": {
            "scenario_id": "phase2-03-database-timeout",
            "request": {"message": "Use the approved synthetic request for this simulation."},
        },
        "review": {"reviewer": "alice", "status": "approved"},
        "configuration_versions": {"workflow_version": "2.0.0"},
    }

    assert scan_payload(payload, context="clean") == ()


def test_scanner_flags_invalid_json_documents() -> None:
    findings = scan_json_text("{not json", context="broken.json")

    assert len(findings) == 1
    assert findings[0].kind == "invalid_json"


def test_forbidden_keys_are_an_explicit_allowlist() -> None:
    assert "password" in FORBIDDEN_KEYS
    assert "api_key" in FORBIDDEN_KEYS
