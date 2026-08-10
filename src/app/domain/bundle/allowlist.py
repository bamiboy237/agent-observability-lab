"""This module defines the privacy allowlist for bundle content.

The compiler rejects unknown fields rather than silently copying them, and it
scans the final bundle for credentials, secrets, authorization headers,
unrestricted private text, and unexpected nested data. The per-resource
allowlist is the authority for owned-system seeds: an approved field such as
a synthetic customer email is accepted, while any field the allowlist does
not name is rejected, and every value must be a JSON scalar. Free-form
fixture payloads and fixture arguments are scanned recursively because they
have no fixed allowlist. The same sensitive-key parts also guard the recorded
simulation adapters, so the two privacy rules cannot diverge.
"""

from collections.abc import Mapping, Sequence

from app.domain.bundle.errors import ForbiddenDataError

# Canonical sensitive key parts shared with the recorded simulation adapters.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "token",
    "authorization",
    "auth_header",
    "credential",
    "credit_card",
    "credit",
    "ssn",
    "email",
    "phone",
    "message",
)

# Per-resource allowlist for owned-system seeds. Values are nested dictionaries
# that map each resource name to the exact set of allowed fields.
RESOURCE_ALLOWLIST: Mapping[str, frozenset[str]] = {
    "customer": frozenset({"id", "name", "email"}),
    "order": frozenset({"id", "customer_id", "status", "total_amount"}),
    "ticket": frozenset({"id", "customer_id", "order_id", "subject", "status"}),
    "policy": frozenset({"id", "slug", "version", "title", "content", "content_hash"}),
}

FORBIDDEN_VALUE_PARTS: tuple[str, ...] = (
    "BEGIN RSA PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN PRIVATE KEY",
    "sk-",
    "api_key=",
    "apikey=",
    "token=",
    "authorization=",
    "credential=",
    "password=",
    "secret=",
    "bearer ",
)

_JSON_SCALARS = (bool, int, float, str)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _contains_forbidden_value(value: str) -> bool:
    lowered = value.lower()
    return any(part.lower() in lowered for part in FORBIDDEN_VALUE_PARTS)


def _contains_forbidden_substring(value: str, substrings: Sequence[str]) -> bool:
    lowered = value.lower()
    return any(substring and substring.lower() in lowered for substring in substrings)


def validate_allowlisted_mapping(
    mapping: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
    context: str,
    forbidden_substrings: Sequence[str] = (),
) -> None:
    """This function rejects unknown fields and forbidden content in one mapping.

    The allowlist is the authority: only allowed fields may appear, every
    value must be a JSON scalar, and string values must not contain forbidden
    substrings, forbidden value parts, or empty strings. An unknown key that
    also looks sensitive is reported with both facts.
    """
    unknown = sorted(set(mapping) - allowed_fields)
    if unknown:
        sensitive_unknown = sorted({key for key in unknown if _is_sensitive_key(key)})
        if sensitive_unknown == unknown:
            raise ForbiddenDataError(
                detail=f"{context} records non-allowlisted sensitive keys {unknown!r}"
            )
        raise ForbiddenDataError(detail=f"{context} records non-allowlisted fields {unknown!r}")
    for key, value in mapping.items():
        if value is None or isinstance(value, _JSON_SCALARS):
            if isinstance(value, str):
                if not value:
                    raise ForbiddenDataError(
                        detail=f"{context} records an empty string for {key!r}"
                    )
                if _contains_forbidden_substring(value, forbidden_substrings):
                    raise ForbiddenDataError(
                        detail=f"{context} records forbidden content in field {key!r}"
                    )
                if _contains_forbidden_value(value):
                    raise ForbiddenDataError(
                        detail=f"{context} records a forbidden value in field {key!r}"
                    )
            continue
        raise ForbiddenDataError(
            detail=(
                f"{context} records a non-scalar value of type {type(value).__name__!r} for {key!r}"
            )
        )


def validate_resource_seed(
    resource: str,
    record: Mapping[str, object],
    *,
    forbidden_substrings: Sequence[str] = (),
) -> None:
    """This function validates one owned-system resource seed record."""
    allowed = RESOURCE_ALLOWLIST.get(resource)
    if allowed is None:
        raise ForbiddenDataError(detail=f"unknown resource type {resource!r}")
    validate_allowlisted_mapping(
        record,
        allowed_fields=allowed,
        context=f"resource {resource!r}",
        forbidden_substrings=forbidden_substrings,
    )


def validate_fixture_payload(
    fixture_type: str,
    payload: object,
    *,
    context: str,
    forbidden_substrings: Sequence[str] = (),
) -> None:
    """This function validates one recorded response payload.

    Only JSON-safe scalars, lists, and dicts are accepted. Any dict key that
    contains a sensitive part is rejected because free-form payloads have no
    fixed allowlist, and every string value is checked for forbidden values
    and forbidden substrings.
    """
    if payload is None:
        return
    if isinstance(payload, _JSON_SCALARS):
        if isinstance(payload, str):
            if _contains_forbidden_value(payload):
                raise ForbiddenDataError(detail=f"{context} records a forbidden value")
            if _contains_forbidden_substring(payload, forbidden_substrings):
                raise ForbiddenDataError(detail=f"{context} records forbidden content")
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            validate_fixture_payload(
                fixture_type,
                item,
                context=f"{context}[{index}]",
                forbidden_substrings=forbidden_substrings,
            )
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _is_sensitive_key(str(key)):
                raise ForbiddenDataError(detail=f"{context} records sensitive key {key!r}")
            validate_fixture_payload(
                fixture_type,
                value,
                context=f"{context}.{key}",
                forbidden_substrings=forbidden_substrings,
            )
        return
    raise ForbiddenDataError(
        detail=f"{context} records non-JSON data of type {type(payload).__name__!r}"
    )


def _scan_fixture_string(value: str, *, context: str, substrings: Sequence[str]) -> None:
    if _contains_forbidden_value(value):
        raise ForbiddenDataError(detail=f"{context} records a forbidden value")
    if _contains_forbidden_substring(value, substrings):
        raise ForbiddenDataError(detail=f"{context} records forbidden content")


def validate_safe_text(
    value: str,
    *,
    context: str,
    forbidden_substrings: Sequence[str] = (),
) -> None:
    """This function rejects secrets and forbidden source text in one string."""
    if not value:
        raise ForbiddenDataError(detail=f"{context} records an empty string")
    _scan_fixture_string(value, context=context, substrings=forbidden_substrings)


def validate_metadata_content(value: object, *, context: str = "bundle metadata") -> None:
    """This function scans typed bundle metadata for secret-like values."""
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        validate_safe_text(value, context=context)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_metadata_content(item, context=f"{context}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            validate_metadata_content(item, context=f"{context}.{key}")
        return
    raise ForbiddenDataError(
        detail=f"{context} records non-JSON data of type {type(value).__name__!r}"
    )


def _scan_fixture_arguments(
    arguments: object,
    *,
    context: str,
    substrings: Sequence[str],
) -> None:
    if arguments is None:
        return
    if not isinstance(arguments, dict):
        raise ForbiddenDataError(detail=f"{context} must be a mapping")
    for key, value in arguments.items():
        if _is_sensitive_key(str(key)):
            raise ForbiddenDataError(detail=f"{context} records sensitive key {key!r}")
        if value is None or isinstance(value, _JSON_SCALARS):
            if isinstance(value, str):
                _scan_fixture_string(value, context=f"{context}.{key}", substrings=substrings)
            continue
        raise ForbiddenDataError(
            detail=(f"{context}.{key} records a non-scalar value of type {type(value).__name__!r}")
        )


def validate_fault_script(
    script: object,
    *,
    allowed_tools: Sequence[str] | None = None,
    allowed_dependencies: Sequence[str] | None = None,
    forbidden_substrings: Sequence[str] = (),
) -> None:
    """This function scans one fault script for unsafe content.

    The scan rejects secret-like values in the tool name and in every
    argument, requires scalar arguments, and optionally rejects fault tools
    that no declared dependency covers. A fault script names the exact
    dependency boundary it wraps: when the declared dependencies are known,
    a script that targets an undeclared dependency is rejected. Successful
    calls must still use the real path, so the script itself only declares
    failures.
    """
    from app.domain.bundle.errors import InvalidBundleFixtureError

    if script is None:
        return
    declared = frozenset(allowed_tools or ())
    dependencies = frozenset(allowed_dependencies or ())
    dependency = getattr(script, "dependency", None)
    if allowed_dependencies is not None and dependency not in dependencies:
        raise InvalidBundleFixtureError(
            detail=(
                f"fault script targets dependency {dependency!r}, which no "
                f"declared dependency {sorted(dependencies)!r} covers"
            )
        )
    entries = getattr(script, "entries", None)
    if entries is None:
        raise ForbiddenDataError(detail="fault script carries no entries")
    for entry in entries:
        tool = entry.tool
        if allowed_tools is not None and tool not in declared:
            raise InvalidBundleFixtureError(
                detail=(
                    f"fault tool {tool!r} is not covered by any declared dependency "
                    f"tool {sorted(declared)!r}"
                )
            )
        _scan_fixture_string(tool, context="fault script tool", substrings=forbidden_substrings)
        _scan_fixture_arguments(
            entry.arguments,
            context=f"fault script {tool!r} arguments",
            substrings=forbidden_substrings,
        )


def scan_bundle_content(
    *,
    resources: Mapping[str, Sequence[Mapping[str, object]]],
    fixtures: Sequence[Mapping[str, object]],
    forbidden_substrings: Sequence[str],
) -> None:
    """This function scans every seed and fixture in the final bundle.

    The scan rejects credentials, secrets, authorization headers,
    unrestricted private text, and unexpected nested data. Each resource
    record is validated against its allowlist with every value required to be
    a JSON scalar. Every fixture field is scanned: identifier strings,
    exact request-matching arguments, and the payload recursively.
    """
    for resource, records in resources.items():
        for record in records:
            validate_resource_seed(
                resource,
                record,
                forbidden_substrings=forbidden_substrings,
            )
    for index, fixture in enumerate(fixtures):
        context = f"fixture {index}"
        fixture_type = str(fixture.get("type", ""))
        for key in ("dependency", "adapter_name", "adapter_version", "tool", "error_code"):
            value = fixture.get(key)
            if isinstance(value, str):
                _scan_fixture_string(
                    value,
                    context=f"{context}.{key}",
                    substrings=forbidden_substrings,
                )
        _scan_fixture_arguments(
            fixture.get("arguments"),
            context=f"{context}.arguments",
            substrings=forbidden_substrings,
        )
        validate_fixture_payload(
            fixture_type,
            fixture.get("payload"),
            context=f"{context} payload",
            forbidden_substrings=forbidden_substrings,
        )
