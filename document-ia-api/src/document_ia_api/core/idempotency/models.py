from enum import Enum
from pydantic import BaseModel, Field


class IdempotencyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class IdempotencyEntry(BaseModel):
    fingerprint: str = Field(description="SHA-256 fingerprint of the request")
    execution_id: str = Field(description="Unique execution ID reserved or completed")
    status: IdempotencyStatus = Field(
        description="Current status of the idempotency record"
    )
    created_at: str = Field(description="ISO-8601 creation timestamp")


class IdempotencyResult(BaseModel):
    is_replay: bool = Field(description="Whether this request is an idempotent replay")
    execution_id: str = Field(
        description="Execution ID associated with the idempotency key"
    )
