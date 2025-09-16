"""Infrastructure health status schemas.

This module contains Pydantic schemas for health check responses
from infrastructure services (Redis, S3, Database, etc.).
"""

from pydantic import BaseModel, Field

from document_ia_api.infra.database.database_connectivity_status import (
    DatabaseConnectivityStatus,
)
from document_ia_api.infra.redis.redis_connectivity_status import (
    RedisConnectivityStatus,
)
from document_ia_api.infra.s3.s3_connectivity_status import S3ConnectivityStatus


class S3HealthStatus(BaseModel):
    """Schema for S3 connectivity health status."""

    connected: bool = Field(description="S3 connection status")
    credentials_valid: bool = Field(description="S3 credentials validation status")
    bucket_exists: bool = Field(description="S3 bucket existence status")
    is_healthy: bool = Field(description="Overall S3 health status")
    errors: list[str] = Field(
        default_factory=list, description="List of S3 connectivity errors"
    )

    @staticmethod
    def from_s3_connectivity_status(s3: S3ConnectivityStatus) -> "S3HealthStatus":
        return S3HealthStatus(
            connected=s3.connected,
            credentials_valid=s3.credentials_valid,
            bucket_exists=s3.bucket_exists,
            is_healthy=s3.is_healthy,
            errors=s3.errors,
        )


class RedisHealthStatus(BaseModel):
    """Schema for Redis connectivity health status."""

    connected: bool = Field(description="Redis connection status")
    is_healthy: bool = Field(description="Overall Redis health status")
    errors: list[str] = Field(
        default_factory=list, description="List of Redis connectivity errors"
    )

    @staticmethod
    def from_redis_connectivity_status(
        redis_connectivity_status: RedisConnectivityStatus,
    ) -> "RedisHealthStatus":
        return RedisHealthStatus(
            connected=redis_connectivity_status.connected,
            is_healthy=redis_connectivity_status.is_healthy,
            errors=redis_connectivity_status.errors,
        )


class DatabaseHealthStatus(BaseModel):
    """Schema for Database connectivity health status."""

    connected: bool = Field(description="Database connection status")
    is_healthy: bool = Field(description="Overall Database health status")
    errors: list[str] = Field(
        default_factory=list, description="List of Database connectivity errors"
    )

    @staticmethod
    def from_database_connectivity_status(
        database_status: DatabaseConnectivityStatus,
    ) -> "DatabaseHealthStatus":
        return DatabaseHealthStatus(
            connected=database_status.connected,
            is_healthy=database_status.is_healthy,
            errors=database_status.errors,
        )
