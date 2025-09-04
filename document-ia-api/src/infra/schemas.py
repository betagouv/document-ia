"""Infrastructure health status schemas.

This module contains Pydantic schemas for health check responses
from infrastructure services (Redis, S3, Database, etc.).
"""

from pydantic import BaseModel, Field


class S3HealthStatus(BaseModel):
    """Schema for S3 connectivity health status."""

    connected: bool = Field(description="S3 connection status")
    credentials_valid: bool = Field(description="S3 credentials validation status")
    bucket_exists: bool = Field(description="S3 bucket existence status")
    is_healthy: bool = Field(description="Overall S3 health status")
    errors: list[str] = Field(
        default_factory=list, description="List of S3 connectivity errors"
    )


class RedisHealthStatus(BaseModel):
    """Schema for Redis connectivity health status."""

    connected: bool = Field(description="Redis connection status")
    is_healthy: bool = Field(description="Overall Redis health status")
    errors: list[str] = Field(
        default_factory=list, description="List of Redis connectivity errors"
    )


class DatabaseHealthStatus(BaseModel):
    """Schema for Database connectivity health status."""

    connected: bool = Field(description="Database connection status")
    is_healthy: bool = Field(description="Overall Database health status")
    errors: list[str] = Field(
        default_factory=list, description="List of Database connectivity errors"
    )
