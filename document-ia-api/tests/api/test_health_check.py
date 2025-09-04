import pytest
from unittest.mock import patch


class TestHealthCheck:
    """Test cases for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, client_with_api_key):
        """Test health check when both S3 and Redis are fully operational."""

        # Mock S3 connectivity check to return healthy status
        mock_s3_connectivity = {
            "connected": True,
            "credentials_valid": True,
            "bucket_exists": True,
            "is_healthy": True,
            "errors": [],
        }

        # Mock Redis connectivity check to return healthy status
        mock_redis_connectivity = {
            "connected": True,
            "is_healthy": True,
            "errors": [],
        }

        with (
            patch("infra.s3_service.s3_service.check_connectivity") as mock_s3_check,
            patch(
                "infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity

            response = client_with_api_key.get("/api/health")

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
    async def test_health_check_unhealthy_s3(self, client_with_api_key):
        """Test health check when S3 is not connected."""

        # Mock S3 connectivity check to return unhealthy status
        mock_s3_connectivity = {
            "connected": False,
            "credentials_valid": False,
            "bucket_exists": False,
            "is_healthy": False,
            "errors": ["S3 credentials not configured properly"],
        }

        # Mock Redis connectivity check to return healthy status
        mock_redis_connectivity = {
            "connected": True,
            "is_healthy": True,
            "errors": [],
        }

        with (
            patch("infra.s3_service.s3_service.check_connectivity") as mock_s3_check,
            patch(
                "infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity

            response = client_with_api_key.get("/api/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_redis_unhealthy(self, client_with_api_key):
        """Test health check when Redis is not connected."""

        # Mock S3 connectivity check to return healthy status
        mock_s3_connectivity = {
            "connected": True,
            "credentials_valid": True,
            "bucket_exists": True,
            "is_healthy": True,
            "errors": [],
        }

        # Mock Redis connectivity check to return unhealthy status
        mock_redis_connectivity = {
            "connected": False,
            "is_healthy": False,
            "errors": ["Redis connection failed"],
        }

        with (
            patch("infra.s3_service.s3_service.check_connectivity") as mock_s3_check,
            patch(
                "infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity

            response = client_with_api_key.get("/api/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_both_unhealthy(self, client_with_api_key):
        """Test health check when both S3 and Redis are unhealthy."""

        # Mock S3 connectivity check to return unhealthy status
        mock_s3_connectivity = {
            "connected": False,
            "credentials_valid": False,
            "bucket_exists": False,
            "is_healthy": False,
            "errors": ["S3 connection failed"],
        }

        # Mock Redis connectivity check to return unhealthy status
        mock_redis_connectivity = {
            "connected": False,
            "is_healthy": False,
            "errors": ["Redis connection failed"],
        }

        with (
            patch("infra.s3_service.s3_service.check_connectivity") as mock_s3_check,
            patch(
                "infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
        ):
            mock_s3_check.return_value = mock_s3_connectivity
            mock_redis_check.return_value = mock_redis_connectivity

            response = client_with_api_key.get("/api/health")

            # Should return 503 when service is unhealthy
            assert response.status_code == 503
            data = response.json()

            assert (
                data["detail"]
                == "Service is currently unavailable - one or more dependencies are unhealthy"
            )

    @pytest.mark.asyncio
    async def test_health_check_s3_exception(self, client_with_api_key):
        """Test health check when S3 connectivity check raises an exception."""

        with (
            patch("infra.s3_service.s3_service.check_connectivity") as mock_s3_check,
            patch(
                "infra.redis_service.redis_service.check_connectivity"
            ) as mock_redis_check,
        ):
            mock_s3_check.side_effect = Exception("S3 service unavailable")
            mock_redis_check.return_value = {
                "connected": True,
                "is_healthy": True,
                "errors": [],
            }

            response = client_with_api_key.get("/api/health")

            # Should return 500 for unexpected exceptions
            assert response.status_code == 500
            data = response.json()
            assert "detail" in data
            assert "Internal Server Error" in data["detail"]
            assert "S3 service unavailable" in data["detail"]
