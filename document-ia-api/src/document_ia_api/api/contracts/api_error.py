from datetime import datetime, timezone
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field, field_serializer


class ApiErrorResponse(BaseModel):
    status: str = Field(default="error", description="Response status")
    error: str = Field(description="Error type")
    message: str = Field(description="Error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error details"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Error timestamp (UTC)",
    )

    # Optional: control JSON serialization format for datetime
    @field_serializer("timestamp")
    def _serialize_timestamp(self, value: datetime) -> str:
        # ISO 8601 with trailing 'Z' for UTC (RFC 3339 style)
        s = value.isoformat()
        return s.replace("+00:00", "Z")
