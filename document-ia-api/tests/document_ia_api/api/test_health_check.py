from unittest.mock import patch

import pytest

from document_ia_api.infra.database.database_connectivity_status import (
    DatabaseConnectivityStatus,
)
from document_ia_api.infra.redis.redis_connectivity_status import (
    RedisConnectivityStatus,
)
from document_ia_api.infra.s3.s3_connectivity_status import S3ConnectivityStatus


class TestHealthCheck:
    """Test cases for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, client_without_api_key):
        """Test health check when both S3 and Redis are fully operational."""

        # Mock S3 connectivity check to return healthy status
        mock_s3_connectivity = TestHealthCheck._getHealthyS3Connectivity()
        mock_db_connectivity = TestHealthCheck._getHealthyDBConnectivity()
        mock_redis_connectivity = TestHealthCheck._getHealthyRedisConnectivity()

        with (
            patch(
                "document_ia_api.infra.s3_service.s3_service.check_connectivity"
            ) as mock_s3_check,
            patch(
                "document_ia_api.infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
            patch(
                "document_ia_api.infra.database_service.database_service.check_database_connectivity"
            ) as mock_db_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity
            mock_db_check.return_value = mock_db_connectivity

            response = client_without_api_key.get("/api/v1/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "healthy"
            assert data["service"] == "Document IA API"
            assert data["version"] == "1.0.0"
            assert "timestamp" in data

            # Check S3 health status
            assert data["s3"]["connected"] is True
            assert data["s3"]["credentials_valid"] is True
            assert data["s3"]["bucket_exists"] is True
            assert data["s3"]["is_healthy"] is True
            assert data["s3"]["errors"] == []

            # Check Redis health status
            assert data["redis"]["connected"] is True
            assert data["redis"]["is_healthy"] is True
            assert data["redis"]["errors"] == []

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_s3(self, client_without_api_key):
        """Test health check when S3 is not connected."""

        # Mock S3 connectivity check to return unhealthy status
        mock_s3_connectivity = TestHealthCheck._getUnhealthyS3Connectivity()
        mock_db_connectivity = TestHealthCheck._getHealthyDBConnectivity()
        mock_redis_connectivity = TestHealthCheck._getHealthyRedisConnectivity()

        with (
            patch(
                "document_ia_api.infra.s3_service.s3_service.check_connectivity"
            ) as mock_s3_check,
            patch(
                "document_ia_api.infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
            patch(
                "document_ia_api.infra.database_service.database_service.check_database_connectivity"
            ) as mock_db_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity
            mock_db_check.return_value = mock_db_connectivity

            response = client_without_api_key.get("/api/v1/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_redis_unhealthy(self, client_without_api_key):
        """Test health check when Redis is not connected."""

        # Mock S3 connectivity check to return healthy status
        mock_s3_connectivity = TestHealthCheck._getHealthyS3Connectivity()
        mock_db_connectivity = TestHealthCheck._getHealthyDBConnectivity()
        # Mock Redis connectivity check to return unhealthy status
        mock_redis_connectivity = TestHealthCheck._getUnhealthyRedisConnectivity()

        with (
            patch(
                "document_ia_api.infra.s3_service.s3_service.check_connectivity"
            ) as mock_s3_check,
            patch(
                "document_ia_api.infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
            patch(
                "document_ia_api.infra.database_service.database_service.check_database_connectivity"
            ) as mock_db_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity
            mock_db_check.return_value = mock_db_connectivity

            response = client_without_api_key.get("/api/v1/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_both_unhealthy(self, client_without_api_key):
        """Test health check when both S3 and Redis are unhealthy."""

        # Mock S3 connectivity check to return unhealthy status
        mock_s3_connectivity = TestHealthCheck._getUnhealthyS3Connectivity()
        mock_db_connectivity = TestHealthCheck._getHealthyDBConnectivity()
        # Mock Redis connectivity check to return unhealthy status
        mock_redis_connectivity = TestHealthCheck._getUnhealthyRedisConnectivity()

        with (
            patch(
                "document_ia_api.infra.s3_service.s3_service.check_connectivity"
            ) as mock_s3_check,
            patch(
                "document_ia_api.infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
            patch(
                "document_ia_api.infra.database_service.database_service.check_database_connectivity"
            ) as mock_db_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity
            mock_db_check.return_value = mock_db_connectivity

            response = client_without_api_key.get("/api/v1/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_s3_exception(self, client_without_api_key):
        """Test health check when S3 connectivity check raises an exception."""

        with (
            patch(
                "document_ia_api.infra.s3_service.s3_service.check_connectivity"
            ) as mock_s3_check,
            patch(
                "document_ia_api.infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
            patch(
                "document_ia_api.infra.database_service.database_service.check_database_connectivity"
            ) as mock_db_check,
        ):
            mock_s3_check.side_effect = Exception("S3 service unavailable")
            mock_redis_check.return_value = (
                TestHealthCheck._getHealthyRedisConnectivity()
            )
            mock_db_check.return_value = TestHealthCheck._getHealthyDBConnectivity()

            response = client_without_api_key.get("/api/v1/health")

            # Should return 500 for unexpected exceptions
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "Internal Server Error" in data["detail"]
            assert "S3 service unavailable" in data["detail"]

    @staticmethod
    def _getHealthyS3Connectivity():
        return S3ConnectivityStatus(
            connected=True,
            endpoint="https://example.com",
            bucket_name="example-bucket",
            credentials_valid=True,
            bucket_exists=True,
            errors=[],
        )

    @staticmethod
    def _getUnhealthyS3Connectivity():
        return S3ConnectivityStatus(
            connected=False,
            endpoint="https://example.com",
            bucket_name="example-bucket",
            credentials_valid=False,
            bucket_exists=False,
            errors=["S3 credentials not configured properly"],
        )

    @staticmethod
    def _getHealthyRedisConnectivity():
        return RedisConnectivityStatus(
            connected=True,
            is_healthy=True,
            db=0,
            host="localhost",
            port=6379,
            errors=[],
        )

    @staticmethod
    def _getUnhealthyRedisConnectivity():
        return RedisConnectivityStatus(
            connected=False,
            is_healthy=False,
            db=0,
            host="localhost",
            port=6379,
            errors=["Redis connection failed"],
        )

    @staticmethod
    def _getHealthyDBConnectivity():
        return DatabaseConnectivityStatus(
            connected=True,
            is_healthy=True,
            errors=[],
        )
