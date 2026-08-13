"""This module scans saved bundles and reports for secrets and forbidden data.

The scan walks every JSON value and flags known secret formats, forbidden
field names, and email addresses. The bundle and event schemas already reject
unknown fields and non-allowlisted attributes; this scanner is the
belt-and-braces audit over stored artifacts and database rows.
"""

import json
import re
from dataclasses import dataclass

Scalar = bool | int | float | str | None

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("github_token", re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("bearer_token", re.compile(r"Bearer [0-9A-Za-z._~+/-]{20,}")),
    ("connection_string", re.compile(r"postgres(?:ql)?://[^\s:]+:[^\s@]+@")),
    (
        "generic_password",
        re.compile(r"(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}"),
    ),
)

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "apiKey",
        "access_token",
        "authorization",
        "private_key",
        "privateKey",
    }
)

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# RFC 2606/6761 reserved domains never carry private data; synthetic
# fixtures use them on purpose, so they are not findings.
RESERVED_EMAIL_DOMAINS: tuple[str, ...] = (
    "example.com",
    "example.org",
    "example.net",
    "example",
    "invalid",
    "test",
    "localhost",
)


@dataclass(frozen=True)
class ScanFinding:
    """This class stores one flagged value inside one scanned payload."""

    context: str
    kind: str
    path: str
    snippet: str


def _flag(value: str, *, context: str, path: str) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    for name, pattern in SECRET_PATTERNS:
        match = pattern.search(value)
        if match is not None:
            findings.append(
                ScanFinding(
                    context=context,
                    kind=name,
                    path=path,
                    snippet=value[max(0, match.start() - 10) : match.end() + 10],
                )
            )
    email_match = EMAIL_PATTERN.search(value)
    if email_match is not None:
        domain = email_match.group(0).rsplit("@", 1)[1].lower()
        reserved = any(
            domain == name or domain.endswith(f".{name}")
            for name in RESERVED_EMAIL_DOMAINS
        )
        if not reserved:
            findings.append(
                ScanFinding(context=context, kind="email", path=path, snippet=value[:120])
            )
    return findings


def scan_payload(payload: object, *, context: str) -> tuple[ScanFinding, ...]:
    """This function scans one parsed JSON payload and returns every finding."""
    findings: list[ScanFinding] = []

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in FORBIDDEN_KEYS:
                    findings.append(
                        ScanFinding(
                            context=context,
                            kind=f"forbidden_key:{key}",
                            path=path or "$",
                            snippet=str(item)[:120],
                        )
                    )
                walk(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            findings.extend(_flag(value, context=context, path=path or "$"))
        elif isinstance(value, (bool, int, float)) or value is None:
            return
        else:
            findings.extend(_flag(str(value), context=context, path=path or "$"))

    walk(payload, "")
    return tuple(findings)


def scan_json_text(text: str, *, context: str) -> tuple[ScanFinding, ...]:
    """This function scans one JSON document and returns every finding."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return (ScanFinding(context=context, kind="invalid_json", path="$", snippet=text[:120]),)
    return scan_payload(payload, context=context)
