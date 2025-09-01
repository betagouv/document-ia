import pytest
from unittest.mock import AsyncMock, patch, Mock
from src.infra.redis_service import RedisService
from src.api.rate_limiting import check_rate_limit, RateLimitMiddleware
from fastcrud.exceptions.http_exceptions import RateLimitException


class TestRateLimiting:
    """Test cases for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self, mock_redis_service):
        """Test that requests within rate limits are allowed."""

        # Mock successful rate limit check
        mock_redis_service.check_rate_limit.return_value = (
            True,
            {
                "limit_exceeded": False,
                "remaining_minute": 299,
                "remaining_daily": 4999,
                "reset_minute": "2024-01-01T12:01:00",
                "reset_daily": "2024-01-02T00:00:00",
            },
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        # Patch the redis_service import in the rate_limiting module
        with patch("src.api.rate_limiting.redis_service", mock_redis_service):
            # Test the rate limit dependency directly
            result = await check_rate_limit(mock_request, "test-api-key")

        assert result["limit_exceeded"] is False
        assert result["remaining_minute"] == 299
        assert result["remaining_daily"] == 4999
        assert mock_request.state.rate_limit_info == result

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, mock_redis_service):
        """Test that requests exceeding rate limits are blocked."""

        # Mock rate limit exceeded
        mock_redis_service.check_rate_limit.return_value = (
            False,
            {
                "limit_exceeded": True,
                "remaining_minute": 0,
                "remaining_daily": 0,
                "reset_minute": "2024-01-01T12:01:00",
                "reset_daily": "2024-01-02T00:00:00",
            },
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        # Patch the redis_service import in the rate_limiting module
        with patch("src.api.rate_limiting.redis_service", mock_redis_service):
            # Test that the dependency raises RateLimitException
            with pytest.raises(RateLimitException) as exc_info:
                await check_rate_limit(mock_request, "test-api-key")

            # The exception should be a RateLimitException
            assert isinstance(exc_info.value, RateLimitException)

    # TODO: add integrations test for rate limited requests
    #  override the rate limit settings for the test (1 request per minute)

    def test_rate_limit_headers_in_response(
        self, client_with_api_key, valid_api_key, mock_redis_service
    ):
        """Test that rate limit headers are included in API responses."""
        # Configure the mock to return specific rate limit info
        mock_redis_service.check_rate_limit.return_value = (
            True,
            {
                "limit_exceeded": False,
                "remaining_minute": 99,
                "remaining_daily": 999,
                "reset_minute": "2024-01-01T12:01:00",
                "reset_daily": "2024-01-02T00:00:00",
            },
        )

        response = client_with_api_key.get(
            "/api/v1/", headers={"X-API-KEY": valid_api_key}
        )

        # The response should exist and include rate limit headers
        assert response.status_code == 200
        assert "X-RateLimit-Remaining-Minute" in response.headers
        assert "X-RateLimit-Remaining-Daily" in response.headers
        assert "X-RateLimit-Reset-Minute" in response.headers
        assert "X-RateLimit-Reset-Daily" in response.headers

        # Verify the header values match our mock
        assert response.headers["X-RateLimit-Remaining-Minute"] == "99"
        assert response.headers["X-RateLimit-Remaining-Daily"] == "999"
        assert response.headers["X-RateLimit-Reset-Minute"] == "2024-01-01T12:01:00"
        assert response.headers["X-RateLimit-Reset-Daily"] == "2024-01-02T00:00:00"

    @pytest.mark.asyncio
    async def test_redis_connection_failure_graceful(self, mock_redis_service):
        """Test that rate limiting gracefully handles Redis connection failures."""

        # Mock Redis connection failure
        mock_redis_service.check_rate_limit.return_value = (
            True,
            {
                "limit_exceeded": False,
                "remaining_minute": 300,
                "remaining_daily": 5000,
                "reset_minute": None,
                "reset_daily": None,
            },
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        # Patch the redis_service import in the rate_limiting module
        with patch("src.api.rate_limiting.redis_service", mock_redis_service):
            # Should still allow the request when Redis is unavailable
            result = await check_rate_limit(mock_request, "test-api-key")

        assert result["limit_exceeded"] is False
        assert result["remaining_minute"] == 300
        assert result["remaining_daily"] == 5000


class TestRedisService:
    """Test cases for Redis service functionality."""

    @pytest.mark.asyncio
    async def test_redis_service_initialization(self):
        """Test Redis service initialization."""
        service = RedisService()
        assert service.redis is None
        assert service.connection_attempts == 0

    @pytest.mark.asyncio
    async def test_redis_service_cleanup(self):
        """Test Redis service cleanup."""
        service = RedisService()
        # Mock Redis connection
        service.redis = AsyncMock()

        await service.close()

        # Verify close was called on Redis connection
        service.redis.close.assert_called_once()


class TestRateLimitMiddleware:
    """Test cases for rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_middleware_adds_headers(self):
        """Test that middleware adds rate limit headers to responses."""

        # Create mock request and response
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.rate_limit_info = {
            "remaining_minute": 299,
            "remaining_daily": 4999,
            "reset_minute": "2024-01-01T12:01:00",
            "reset_daily": "2024-01-02T00:00:00",
        }

        mock_response = Mock()
        mock_response.headers = {}

        # Mock call_next function
        async def mock_call_next(request):
            return mock_response

        # Create middleware instance
        middleware = RateLimitMiddleware(Mock())

        # Call dispatch
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Verify headers were added
        assert response.headers["X-RateLimit-Remaining-Minute"] == "299"
        assert response.headers["X-RateLimit-Remaining-Daily"] == "4999"
        assert response.headers["X-RateLimit-Reset-Minute"] == "2024-01-01T12:01:00"
        assert response.headers["X-RateLimit-Reset-Daily"] == "2024-01-02T00:00:00"

    @pytest.mark.asyncio
    async def test_middleware_no_rate_limit_info(self):
        """Test that middleware handles requests without rate limit info."""

        # Create mock request and response without rate limit info
        mock_request = Mock()
        mock_request.state = Mock()
        # Explicitly set rate_limit_info to None to simulate no rate limit info
        mock_request.state.rate_limit_info = None

        mock_response = Mock()
        mock_response.headers = {}

        # Mock call_next function
        async def mock_call_next(request):
            return mock_response

        # Create middleware instance
        middleware = RateLimitMiddleware(Mock())

        # Call dispatch
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Verify no headers were added
        assert "X-RateLimit-Remaining-Minute" not in response.headers
        assert "X-RateLimit-Remaining-Daily" not in response.headers
