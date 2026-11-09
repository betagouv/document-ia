from typing import Annotated, Optional, TypeAlias, TypeVar, Generic, Any

from pydantic import SecretStr, SecretBytes, BeforeValidator, GetCoreSchemaHandler
from pydantic.functional_serializers import PlainSerializer
from pydantic_core import core_schema

V = TypeVar("V")


class SecretDict(Generic[V]):
    def __init__(self, inner_dict: dict[str, V]) -> None:
        self.inner_dict = inner_dict

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.is_instance_schema(cls)

    def get_secret_value(self) -> dict[str, V]:
        return self.inner_dict

    def items(self):
        return self.inner_dict.items()

    def keys(self):
        return self.inner_dict.keys()

    def values(self):
        return self.inner_dict.values()

    def get(self, key: str, default: Any = None) -> Any:
        return self.inner_dict.get(key, default)

    def __getitem__(self, key: str) -> V:
        return self.inner_dict[key]

    def __contains__(self, key: object) -> bool:
        return key in self.inner_dict

    def __len__(self) -> int:
        return len(self.inner_dict)

    def __iter__(self):
        return iter(self.inner_dict)

    def __bool__(self) -> bool:
        return bool(self.inner_dict)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretDict):
            return self.inner_dict == other.inner_dict  # type: ignore[reportUnknownMemberType]
        if isinstance(other, dict):
            return self.inner_dict == other
        return False

    def __str__(self):
        items: list[str] = []
        for k, _ in self.inner_dict.items():
            items.append(f"{repr(k)}: ***")
        return "{" + ", ".join(items) + "}"

    def __repr__(self):
        items: list[str] = []
        for k in self.inner_dict.keys():
            items.append(f"{repr(k)}: ***")
        return f"{self.__class__.__name__}(" + "{" + ", ".join(items) + "})"


def _to_secret_dict(v: Any) -> SecretDict[V]:  # type: ignore[arg-type]
    if v is None:
        return SecretDict({})  # type: ignore[arg-type]
    if isinstance(v, SecretDict):
        return v  # type: ignore[arg-type]
    if isinstance(v, dict):
        return SecretDict(v)  # type: ignore[arg-type]
    raise TypeError("expected dict or SecretDict")


def _secret_dict_to_json(v: Optional[SecretDict[V]]) -> dict[str, V]:
    if v is None:
        return {}
    try:
        return v.inner_dict
    except Exception:
        return {}


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
type SecretPayloadDict[T] = Annotated[
    SecretDict[T],
    BeforeValidator(_to_secret_dict),
    PlainSerializer(_secret_dict_to_json, when_used="json"),
]
