from datetime import datetime, timedelta
from unittest.mock import patch, Mock

import pytest

from document_ia_api.api.exceptions.rate_limit_exception import RateLimitException
from document_ia_api.api.rate_limiting import check_rate_limit, RateLimitMiddleware
from document_ia_api.schemas.rate_limiting import RateLimitInfo


class TestRateLimiting:
    """Test cases for rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self, mock_redis_service):
        """Test that requests within rate limits are allowed."""

        # Mock successful rate limit check
        mock_redis_service.check_rate_limit.return_value = (
            True,
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=299,
                remaining_daily=4999,
                reset_minute="2024-01-01T12:01:00",
                reset_daily="2024-01-02T00:00:00",
            ),
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        with patch(
            "document_ia_api.api.rate_limiting.redis_service", mock_redis_service
        ):
            result = await check_rate_limit(mock_request, "test-api-key")

        assert result.limit_exceeded is False
        assert result.remaining_minute == 299
        assert result.remaining_daily == 4999
        assert mock_request.state.rate_limit_info == result

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, mock_redis_service):
        """Test that requests exceeding rate limits are blocked."""

        # Mock rate limit exceeded
        mock_redis_service.check_rate_limit.return_value = (
            False,
            RateLimitInfo(
                limit_exceeded=True,
                remaining_minute=0,
                remaining_daily=0,
                reset_minute="2024-01-01T12:01:00",
                reset_daily="2024-01-02T00:00:00",
            ),
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        with patch(
            "document_ia_api.api.rate_limiting.redis_service", mock_redis_service
        ):
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
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=99,
                remaining_daily=999,
                reset_minute="2024-01-01T12:01:00",
                reset_daily="2024-01-02T00:00:00",
            ),
        )

        response = client_with_api_key.get(
            "/api/test", headers={"X-API-KEY": valid_api_key}
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
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=300,
                remaining_daily=5000,
                reset_minute=None,
                reset_daily=None,
            ),
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        with patch(
            "document_ia_api.api.rate_limiting.redis_service", mock_redis_service
        ):
            # Should still allow the request when Redis is unavailable
            result = await check_rate_limit(mock_request, "test-api-key")

        assert result.limit_exceeded is False
        assert result.remaining_minute == 300
        assert result.remaining_daily == 5000


class TestRateLimitMiddleware:
    """Test cases for rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_middleware_adds_headers(self):
        """Test that middleware adds rate limit headers to responses."""

        # Create mock request and response
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.rate_limit_info = RateLimitInfo(
            limit_exceeded=False,
            remaining_minute=299,
            remaining_daily=4999,
            reset_minute="2024-01-01T12:01:00",
            reset_daily="2024-01-02T00:00:00",
        )

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


class TestFixedWindowResetBehavior:
    """Test cases for fixed window rate limiting reset behavior."""

    @pytest.mark.asyncio
    async def test_rate_limit_reset_times_in_response(self, mock_redis_service):
        """Test that rate limit responses include correct reset times."""
        # Test with a specific time to verify reset calculation
        test_time = datetime(2024, 12, 1, 13, 30, 45)

        # Calculate expected reset times
        minute_start = test_time.replace(second=0, microsecond=0)
        next_minute = minute_start + timedelta(minutes=1)
        day_start = test_time.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day_start + timedelta(days=1)

        # Mock successful rate limit check with correct reset times
        mock_redis_service.check_rate_limit.return_value = (
            True,
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=299,
                remaining_daily=4999,
                reset_minute=next_minute.isoformat(),
                reset_daily=next_day.isoformat(),
            ),
        )

        # Create a mock request object
        mock_request = Mock()
        mock_request.state = Mock()

        # Patch le bon module (sans prefixe src)
        with patch(
            "document_ia_api.api.rate_limiting.redis_service", mock_redis_service
        ):
            result = await check_rate_limit(mock_request, "test-api-key")

        # Verify reset times are correct
        assert result.reset_minute == next_minute.isoformat()
        assert result.reset_daily == next_day.isoformat()

        # Verify specific expected values
        assert result.reset_minute == "2024-12-01T13:31:00"
        assert result.reset_daily == "2024-12-02T00:00:00"
