from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from infra.schemas import S3HealthStatus, RedisHealthStatus, DatabaseHealthStatus


class APIStatusResponse(BaseModel):
    """Schema for API status response."""

    status: str = Field(description="API status", examples=["success"])
    message: str = Field(
        description="Status message", examples=["Document IA API is running"]
    )
    version: str = Field(description="API version", examples=["1.0.0"])
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Response timestamp",
    )


class HealthCheckResponse(BaseModel):
    """Schema for health check response."""

    status: str = Field(description="Health status", examples=["healthy", "unhealthy"])
    timestamp: str = Field(description="Health check timestamp")
    service: str = Field(description="Service name", examples=["Document IA API"])
    version: str = Field(description="Service version", examples=["1.0.0"])
    s3: S3HealthStatus = Field(description="S3 connectivity health status")
    redis: RedisHealthStatus = Field(description="Redis connectivity health status")
    database: DatabaseHealthStatus = Field(
        description="Database connectivity health status"
    )


class ErrorResponse(BaseModel):
    """Schema for error responses."""

    status: str = Field(
        default="error", description="Response status", examples=["error"]
    )
    error: str = Field(
        description="Error type",
        examples=["ValidationError", "AuthenticationError", "RateLimitError"],
    )
    message: str = Field(
        description="Error message",
        examples=["Invalid request data", "API key is required", "Rate limit exceeded"],
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error details"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Error timestamp",
    )
    request_id: Optional[str] = Field(
        default=None, description="Request correlation ID for debugging"
    )


class RateLimitResponse(BaseModel):
    """Schema for rate limit information."""

    limit: int = Field(description="Rate limit per time window")
    remaining: int = Field(description="Remaining requests in current window")
    reset_time: str = Field(description="Time when rate limit resets")
    retry_after: Optional[int] = Field(
        default=None,
        description="Seconds to wait before retrying (when limit exceeded)",
    )
