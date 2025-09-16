from typing import Optional
from pydantic import BaseModel, Field


class RateLimitInfo(BaseModel):
    """Schema for rate limiting information."""

    limit_exceeded: bool = Field(description="Whether the rate limit has been exceeded")
    remaining_minute: int = Field(
        ge=0, description="Number of requests remaining in the current minute"
    )
    remaining_daily: int = Field(
        ge=0, description="Number of requests remaining in the current day"
    )
    reset_minute: Optional[str] = Field(
        default=None, description="ISO format timestamp when the minute limit resets"
    )
    reset_daily: Optional[str] = Field(
        default=None, description="ISO format timestamp when the daily limit resets"
    )
