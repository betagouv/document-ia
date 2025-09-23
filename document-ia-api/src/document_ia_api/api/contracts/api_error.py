from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class ApiErrorResponse(BaseModel):
    status: str = Field(default="error", description="Response status")
    error: str = Field(description="Error type")
    message: str = Field(description="Error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error details"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Error timestamp",
    )
