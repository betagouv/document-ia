from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from document_ia_api.api.exceptions.rate_limit_exception import RateLimitException
from document_ia_api.api.middleware.rate_limiting_middleware import (
    RateLimitMiddleware,
    check_rate_limit,
)
from document_ia_api.infra.redis_service import RedisService
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus

RATE_LIMITING_MODULE = "document_ia_api.api.middleware.rate_limiting_middleware"
REDIS_SERVICE_PATH = f"{RATE_LIMITING_MODULE}.redis_service"


@pytest.fixture
def sample_api_key_dto() -> ApiKeyDTO:
    now = datetime.now()
    return ApiKeyDTO(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        organization_id=UUID("87654321-4321-8765-4321-876543210987"),
        organization=None,
        key_hash="argon2$dummy_hash",
        prefix="testpref",
        status=ApiKeyStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


class TestRateLimiting:
    """Test cases for rate limiting middleware dependency."""

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self, mock_redis_service, sample_api_key_dto):
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

        with patch(REDIS_SERVICE_PATH, mock_redis_service):
            result = await check_rate_limit(mock_request, sample_api_key_dto)

        assert result.limit_exceeded is False
        assert result.remaining_minute == 299
        assert result.remaining_daily == 4999
        assert mock_request.state.rate_limit_info == result
        mock_redis_service.check_rate_limit.assert_awaited_once_with(
            sample_api_key_dto.id
        )

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, mock_redis_service, sample_api_key_dto):
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

        with patch(REDIS_SERVICE_PATH, mock_redis_service):
            # Test that the dependency raises RateLimitException
            with pytest.raises(RateLimitException) as exc_info:
                await check_rate_limit(mock_request, sample_api_key_dto)

            assert isinstance(exc_info.value, RateLimitException)
            assert "Retry-After" in exc_info.value.headers
        mock_redis_service.check_rate_limit.assert_awaited_once_with(
            sample_api_key_dto.id
        )

    def test_rate_limit_headers_in_response(
        self, client_with_api_key_standard, standard_api_key_value, mock_redis_service
    ):
        """Test that rate limit headers are included in API responses."""
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

        response = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": standard_api_key_value}
        )

        assert response.status_code == 200
        assert "X-RateLimit-Remaining-Minute" in response.headers
        assert "X-RateLimit-Remaining-Daily" in response.headers
        assert "X-RateLimit-Reset-Minute" in response.headers
        assert "X-RateLimit-Reset-Daily" in response.headers

        assert response.headers["X-RateLimit-Remaining-Minute"] == "99"
        assert response.headers["X-RateLimit-Remaining-Daily"] == "999"
        assert response.headers["X-RateLimit-Reset-Minute"] == "2024-01-01T12:01:00"
        assert response.headers["X-RateLimit-Reset-Daily"] == "2024-01-02T00:00:00"


class TestRateLimitMiddleware:
    """Test cases for rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_middleware_adds_headers(self):
        """Test that middleware adds rate limit headers to responses."""
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

        async def mock_call_next(request):
            return mock_response

        middleware = RateLimitMiddleware(Mock())
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.headers["X-RateLimit-Remaining-Minute"] == "299"
        assert response.headers["X-RateLimit-Remaining-Daily"] == "4999"
        assert response.headers["X-RateLimit-Reset-Minute"] == "2024-01-01T12:01:00"
        assert response.headers["X-RateLimit-Reset-Daily"] == "2024-01-02T00:00:00"

    @pytest.mark.asyncio
    async def test_middleware_no_rate_limit_info(self):
        """Test that middleware handles requests without rate limit info."""
        mock_request = Mock()
        mock_request.state = Mock()
        mock_request.state.rate_limit_info = None

        mock_response = Mock()
        mock_response.headers = {}

        async def mock_call_next(request):
            return mock_response

        middleware = RateLimitMiddleware(Mock())
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert "X-RateLimit-Remaining-Minute" not in response.headers
        assert "X-RateLimit-Remaining-Daily" not in response.headers


class TestFixedWindowResetBehavior:
    """Test cases for fixed window rate limiting reset behavior."""

    @pytest.mark.asyncio
    async def test_rate_limit_reset_times_in_response(
        self, mock_redis_service, sample_api_key_dto
    ):
        """Test that rate limit responses include correct reset times."""
        test_time = datetime(2024, 12, 1, 13, 30, 45)

        minute_start = test_time.replace(second=0, microsecond=0)
        next_minute = minute_start + timedelta(minutes=1)
        day_start = test_time.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day_start + timedelta(days=1)

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

        mock_request = Mock()
        mock_request.state = Mock()

        with patch(REDIS_SERVICE_PATH, mock_redis_service):
            result = await check_rate_limit(mock_request, sample_api_key_dto)

        assert result.reset_minute == next_minute.isoformat()
        assert result.reset_daily == next_day.isoformat()
        assert result.reset_minute == "2024-12-01T13:31:00"
        assert result.reset_daily == "2024-12-02T00:00:00"


class TestRedisServiceRateLimiting:
    """Test cases for RedisService check_rate_limit implementation (Issue #154)."""

    def _setup_mock_connection(self, minute_count: int = 1, daily_count: int = 1):
        connection = MagicMock()
        pipe = AsyncMock()
        pipe.execute.return_value = [
            minute_count,
            True,
            daily_count,
            True,
            str(minute_count),
            str(daily_count),
        ]
        connection.pipeline.return_value.__aenter__.return_value = pipe
        return connection, pipe

    @pytest.mark.asyncio
    async def test_redis_keys_use_uuid_and_no_secret_in_keys(
        self, monkeypatch, sample_api_key_dto
    ):
        """Verify that Redis keys exclusively use the UUID identifier and never the raw secret or prefix."""
        connection, pipe = self._setup_mock_connection(minute_count=5, daily_count=10)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        is_allowed, info = await service.check_rate_limit(sample_api_key_dto.id)

        assert is_allowed is True
        assert info.limit_exceeded is False

        # Verify pipe.incr calls
        incr_calls = pipe.incr.call_args_list
        assert len(incr_calls) == 2
        minute_key = incr_calls[0].args[0]
        daily_key = incr_calls[1].args[0]

        expected_uuid_str = str(sample_api_key_dto.id)
        assert minute_key.startswith(f"rate_limit:minute:{expected_uuid_str}:")
        assert daily_key.startswith(f"rate_limit:daily:{expected_uuid_str}:")

        # Explicitly verify secret and prefix are NOT in the keys
        assert sample_api_key_dto.prefix not in minute_key
        assert sample_api_key_dto.prefix not in daily_key
        assert "argon2" not in minute_key
        assert "argon2" not in daily_key

        # Verify TTLs
        expire_calls = pipe.expire.call_args_list
        assert len(expire_calls) == 2
        assert expire_calls[0].args == (minute_key, 60)
        assert expire_calls[1].args == (daily_key, 86400)

    @pytest.mark.asyncio
    async def test_same_key_shares_same_redis_budget(self, monkeypatch):
        """Verify that multiple checks for the same UUID share the exact same Redis keys."""
        connection, pipe = self._setup_mock_connection(minute_count=1, daily_count=1)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        key_uuid = uuid4()

        # First call with UUID object
        await service.check_rate_limit(key_uuid)
        first_minute_key = pipe.incr.call_args_list[0].args[0]
        first_daily_key = pipe.incr.call_args_list[1].args[0]

        # Second call with str(UUID)
        await service.check_rate_limit(str(key_uuid))
        second_minute_key = pipe.incr.call_args_list[2].args[0]
        second_daily_key = pipe.incr.call_args_list[3].args[0]

        assert first_minute_key == second_minute_key
        assert first_daily_key == second_daily_key

    @pytest.mark.asyncio
    async def test_different_keys_have_independent_redis_budgets(self, monkeypatch):
        """Verify that two distinct keys get different Redis keys."""
        connection, pipe = self._setup_mock_connection(minute_count=1, daily_count=1)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        key_1 = uuid4()
        key_2 = uuid4()

        await service.check_rate_limit(key_1)
        k1_minute = pipe.incr.call_args_list[0].args[0]
        k1_daily = pipe.incr.call_args_list[1].args[0]

        await service.check_rate_limit(key_2)
        k2_minute = pipe.incr.call_args_list[2].args[0]
        k2_daily = pipe.incr.call_args_list[3].args[0]

        assert k1_minute != k2_minute
        assert k1_daily != k2_daily
        assert str(key_1) in k1_minute
        assert str(key_2) in k2_minute

    @pytest.mark.asyncio
    async def test_different_keys_same_organization_have_independent_budgets(
        self, monkeypatch
    ):
        """Verify that two distinct API keys for the same organization have independent Redis budgets."""
        connection, pipe = self._setup_mock_connection(minute_count=1, daily_count=1)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        same_org_id = uuid4()
        key_dto_1 = ApiKeyDTO(
            id=uuid4(),
            organization_id=same_org_id,
            organization=None,
            key_hash="hash1",
            prefix="KEY1",
            status=ApiKeyStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        key_dto_2 = ApiKeyDTO(
            id=uuid4(),
            organization_id=same_org_id,
            organization=None,
            key_hash="hash2",
            prefix="KEY2",
            status=ApiKeyStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        await service.check_rate_limit(key_dto_1.id)
        k1_minute = pipe.incr.call_args_list[0].args[0]
        k1_daily = pipe.incr.call_args_list[1].args[0]

        await service.check_rate_limit(key_dto_2.id)
        k2_minute = pipe.incr.call_args_list[2].args[0]
        k2_daily = pipe.incr.call_args_list[3].args[0]

        assert k1_minute != k2_minute
        assert k1_daily != k2_daily
        assert str(key_dto_1.id) in k1_minute
        assert str(key_dto_2.id) in k2_minute

    @pytest.mark.asyncio
    async def test_redis_outage_fails_closed_with_503(self, monkeypatch):
        """Verify that Redis outage raises 503 capacity_unavailable (fail-closed, #149)."""
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(side_effect=ConnectionError("Redis down")),
        )

        service = RedisService()
        with pytest.raises(HTTPException) as exc_info:
            await service.check_rate_limit(uuid4())

        assert exc_info.value.status_code == 503
        assert "Retry-After" in exc_info.value.headers


class TestRateLimitingAuthIntegration:
    """Test integration between authentication and rate limiting."""

    def test_invalid_api_key_fails_401_without_redis_call(
        self, client_with_api_key_invalid, invalid_api_key_value, mock_redis_service
    ):
        """Verify that invalid API key is rejected with 401 without any Redis call."""
        response = client_with_api_key_invalid.get(
            "/api/test", headers={"X-API-KEY": invalid_api_key_value}
        )

        assert response.status_code == 401
        mock_redis_service.check_rate_limit.assert_not_called()

    def test_missing_api_key_fails_401_without_redis_call(
        self, client_without_api_key, mock_redis_service
    ):
        """Verify that missing API key is rejected with 401 without any Redis call."""
        response = client_without_api_key.get("/api/test")

        assert response.status_code == 401
        mock_redis_service.check_rate_limit.assert_not_called()

    def test_valid_api_key_calls_rate_limit_with_key_uuid(
        self, client_with_api_key_standard, standard_api_key_value, mock_redis_service
    ):
        """Verify that valid API key triggers rate limit check using its internal UUID."""
        response = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": standard_api_key_value}
        )

        assert response.status_code == 200
        mock_redis_service.check_rate_limit.assert_called_once()
        called_key_id = mock_redis_service.check_rate_limit.call_args[0][0]
        assert isinstance(called_key_id, UUID)
