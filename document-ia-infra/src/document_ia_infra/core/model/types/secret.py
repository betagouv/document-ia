from typing import Annotated, Optional, TypeAlias

from pydantic import SecretStr, SecretBytes
from pydantic.functional_serializers import PlainSerializer


def _secret_str_to_json(v: Optional[SecretStr]) -> Optional[str]:
    if v is None:
        return None
    try:
        return v.get_secret_value()
    except Exception:
        return str(v)


def _secret_bytes_to_json(v: Optional[SecretBytes]) -> Optional[bytes]:
    if v is None:
        return None
    try:
        return v.get_secret_value()
    except Exception:
        # Avoid raising in serialization; return raw repr
        raw = v.get_secret_value() if hasattr(v, "get_secret_value") else v
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return str(raw).encode()


# Public aliases to use in contracts/models
# Use those aliases instead of SecretStr/SecretBytes directly
# to ensure proper serialization in JSON contexts
# they will be clear in json output but hided in logs.
SecretPayloadStr: TypeAlias = Annotated[
    SecretStr,
    PlainSerializer(_secret_str_to_json, when_used="json"),
]
SecretPayloadBytes: TypeAlias = Annotated[
    SecretBytes,
    PlainSerializer(_secret_bytes_to_json, when_used="json"),
]
