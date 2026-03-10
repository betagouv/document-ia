from enum import Enum


class AnonymizationStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    ERROR = "ERROR"

    @classmethod
    def from_str(cls, value: str) -> "AnonymizationStatus":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"Unknown event type: {value}")

    def __str__(self) -> str:
        return self.value
