from typing import Protocol


class SerializableMessage(Protocol):
    def to_dict(self) -> dict: ...
