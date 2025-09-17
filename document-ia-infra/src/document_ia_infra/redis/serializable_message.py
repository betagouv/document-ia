from typing import Protocol, Any


class SerializableMessage(Protocol):
    def to_dict(self) -> dict[str, Any]: ...
    @staticmethod
    def from_json(data: str) -> "SerializableMessage": ...
