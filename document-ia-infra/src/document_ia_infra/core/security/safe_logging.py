import ipaddress
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

ALLOWED_REQUEST_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "content-length",
        "user-agent",
        "accept",
        "accept-encoding",
        "host",
        "x-request-id",
    }
)

ALLOWED_RESPONSE_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "content-length",
        "x-request-id",
        "idempotent-replay",  # Preshot to support seamless integration with #148
    }
)

ALLOWED_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "limit",
        "offset",
        "page",
        "status",
        "sort",
        "order",
        "direction",
        "workflow_id",
        "execution_id",
    }
)

ALLOWED_PATH_PARAMS: frozenset[str] = frozenset(
    {
        "execution_id",
        "organization_id",
        "workflow_id",
        "webhook_id",
        "task_id",
        "version",
    }
)

ALLOWED_STEP_METADATA_FIELDS: frozenset[str] = frozenset(
    {
        "step_name",
        "execution_time",
        "request_tokens",
        "response_tokens",
        "model",
    }
)

MASKED_VALUE: str = "**********"

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_HOSTNAME_RE = re.compile(
    r"^(?:localhost|(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63})$"
)


def _is_valid_host(hostname: str) -> bool:
    raw_host = hostname.strip("[]")
    if _HOSTNAME_RE.match(raw_host):
        return True
    try:
        ipaddress.ip_address(raw_host)
        return True
    except ValueError:
        return False


def filter_headers(
    headers: Mapping[str, str],
    allowed: frozenset[str] = ALLOWED_REQUEST_HEADERS,
) -> dict[str, str]:
    """Filters headers case-insensitively, keeping only explicitly allowed headers.

    Returned keys are normalized to lowercase.
    """
    return {k.lower(): v for k, v in headers.items() if k.lower() in allowed}


def filter_query_params(
    query: Mapping[str, Any],
    allowed: frozenset[str] = ALLOWED_QUERY_PARAMS,
    mask: str = MASKED_VALUE,
) -> dict[str, Any]:
    """Filters query parameters.

    Allowed parameters are preserved, while any parameter absent from the
    allowlist is masked with the specified placeholder.
    """
    return {k: (v if k.lower() in allowed else mask) for k, v in query.items()}


def filter_path_params(
    path: Mapping[str, Any],
    allowed: frozenset[str] = ALLOWED_PATH_PARAMS,
) -> dict[str, Any]:
    """Filters path parameters to only retain allowed keys."""
    return {k: v for k, v in path.items() if k.lower() in allowed}


def extract_safe_host(url: str | None) -> str:
    """Extracts only the safe hostname (and port if non-standard) from a URL.

    Strips any credentials (user:password@), path, query parameters, and fragments.
    Returns 'unknown' if url is None, empty, unparseable, or not a valid host.
    """
    if not url:
        return "unknown"

    cleaned = url.strip()
    if not cleaned:
        return "unknown"

    if any(c in cleaned for c in ("\r", "\n", "\0")):
        return "unknown"

    if not _SCHEME_RE.match(cleaned) and not cleaned.startswith("//"):
        cleaned = f"//{cleaned}"

    try:
        parsed = urlsplit(cleaned)
        hostname = parsed.hostname
        if not hostname or not _is_valid_host(hostname):
            return "unknown"
        port = parsed.port
        if port and port not in (80, 443):
            if ":" in hostname:
                return f"[{hostname}]:{port}"
            return f"{hostname}:{port}"
        return hostname
    except Exception:
        return "unknown"
