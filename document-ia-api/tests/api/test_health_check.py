import pytest
from unittest.mock import patch


class TestHealthCheck:
    """Test cases for health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, client_with_api_key):
        """Test health check when S3 is fully operational."""

        # Mock S3 connectivity check to return healthy status
        mock_s3_connectivity = {
            "connected": True,
            "credentials_valid": True,
            "bucket_exists": True,
            "errors": [],
        }

        with patch("infra.s3_service.s3_service.check_connectivity") as mock_check:
            mock_check.return_value = mock_s3_connectivity

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
            assert data["s3"]["errors"] == []

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, client_with_api_key):
        """Test health check when S3 is not connected."""

        # Mock S3 connectivity check to return unhealthy status
        mock_s3_connectivity = {
            "connected": False,
            "credentials_valid": False,
            "bucket_exists": False,
            "errors": ["S3 credentials not configured properly"],
        }

        with patch("infra.s3_service.s3_service.check_connectivity") as mock_check:
            mock_check.return_value = mock_s3_connectivity

            response = client_with_api_key.get("/api/health")

            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "unhealthy"
            assert data["s3"]["connected"] is False
            assert data["s3"]["credentials_valid"] is False
            assert data["s3"]["bucket_exists"] is False
            assert len(data["s3"]["errors"]) > 0

    @pytest.mark.asyncio
    async def test_health_check_s3_exception(self, client_with_api_key):
        """Test health check when S3 connectivity check raises an exception."""

        with patch("infra.s3_service.s3_service.check_connectivity") as mock_check:
            mock_check.side_effect = Exception("S3 service unavailable")

            response = client_with_api_key.get("/api/health")

            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            assert "unavailable" in data["detail"]

    def test_health_check_no_authentication_required(self, client_with_api_key):
        """Test that health check endpoint doesn't require authentication."""

        # Mock S3 connectivity check
        mock_s3_connectivity = {
            "connected": True,
            "credentials_valid": True,
            "bucket_exists": True,
            "errors": [],
        }

        with patch("infra.s3_service.s3_service.check_connectivity") as mock_check:
            mock_check.return_value = mock_s3_connectivity

            # Make request without any authentication headers
            response = client_with_api_key.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
