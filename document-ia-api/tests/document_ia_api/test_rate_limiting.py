import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from document_ia_api.api.exceptions.rate_limit_exception import RateLimitException
from document_ia_api.api.exceptions.service_unavailable_exception import (
    capacity_unavailable,
)
from document_ia_api.api.middleware.rate_limiting_middleware import (
    RateLimitMiddleware,
    check_rate_limit,
)
from document_ia_api.infra.config import settings
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


class InMemoryRateLimitConnection:
    """Simulates Redis connection executing RATE_LIMIT_SCRIPT atomically."""

    def __init__(self, minute_limit: int = 300, daily_limit: int = 5000):
        self.minute_limit = minute_limit
        self.daily_limit = daily_limit
        self.counters: dict[str, int] = {}
        self.lock = asyncio.Lock()

    def pipeline(self):
        return InMemoryRateLimitPipeline(self)


class InMemoryRateLimitPipeline:
    def __init__(self, conn: InMemoryRateLimitConnection):
        self.conn = conn
        self.eval_calls: list[tuple] = []
        self.results: list[list[int]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def eval(
        self,
        script: str,
        numkeys: int,
        minute_key: str,
        daily_key: str,
        minute_limit: int,
        daily_limit: int,
        minute_ttl: int,
        daily_ttl: int,
    ) -> None:
        self.eval_calls.append(
            (
                script,
                numkeys,
                minute_key,
                daily_key,
                minute_limit,
                daily_limit,
                minute_ttl,
                daily_ttl,
            )
        )
        async with self.conn.lock:
            min_count = self.conn.counters.get(minute_key, 0)
            day_count = self.conn.counters.get(daily_key, 0)
            if min_count >= int(minute_limit) or day_count >= int(daily_limit):
                self.results.append([0, min_count, day_count])
            else:
                min_count += 1
                day_count += 1
                self.conn.counters[minute_key] = min_count
                self.conn.counters[daily_key] = day_count
                self.results.append([1, min_count, day_count])

    async def execute(self) -> list[list[int]]:
        res = list(self.results)
        self.results.clear()
        return res


class TestRedisServiceRateLimiting:
    """Test cases for RedisService check_rate_limit implementation (Issue #154)."""

    def _setup_mock_connection(
        self, allowed: int = 1, minute_count: int = 1, daily_count: int = 1
    ):
        connection = MagicMock()
        pipe = AsyncMock()
        pipe.execute.return_value = [[allowed, minute_count, daily_count]]
        connection.pipeline.return_value.__aenter__.return_value = pipe
        return connection, pipe

    @pytest.mark.asyncio
    async def test_redis_keys_use_uuid_and_no_secret_in_keys(
        self, monkeypatch, sample_api_key_dto
    ):
        """Verify that Redis keys exclusively use the UUID identifier and never the raw secret or prefix."""
        connection, pipe = self._setup_mock_connection(
            allowed=1, minute_count=5, daily_count=10
        )
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        is_allowed, info = await service.check_rate_limit(sample_api_key_dto.id)

        assert is_allowed is True
        assert info.limit_exceeded is False

        # Verify pipe.eval call
        eval_calls = pipe.eval.call_args_list
        assert len(eval_calls) == 1
        (
            script,
            numkeys,
            minute_key,
            daily_key,
            min_limit,
            day_limit,
            min_ttl,
            day_ttl,
        ) = eval_calls[0].args
        assert numkeys == 2
        assert min_ttl == "60"
        assert day_ttl == "86400"

        expected_uuid_str = str(sample_api_key_dto.id)
        assert minute_key.startswith(f"rate_limit:minute:{expected_uuid_str}:")
        assert daily_key.startswith(f"rate_limit:daily:{expected_uuid_str}:")

        # Explicitly verify secret and prefix are NOT in the keys
        assert sample_api_key_dto.prefix not in minute_key
        assert sample_api_key_dto.prefix not in daily_key
        assert "argon2" not in minute_key
        assert "argon2" not in daily_key

    @pytest.mark.asyncio
    async def test_same_key_shares_same_redis_budget(self, monkeypatch):
        """Verify that multiple checks for the same UUID share the exact same Redis keys."""
        connection, pipe = self._setup_mock_connection(
            allowed=1, minute_count=1, daily_count=1
        )
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        key_uuid = uuid4()

        # First call with UUID object
        await service.check_rate_limit(key_uuid)
        first_minute_key = pipe.eval.call_args_list[0].args[2]
        first_daily_key = pipe.eval.call_args_list[0].args[3]

        # Second call with str(UUID)
        await service.check_rate_limit(str(key_uuid))
        second_minute_key = pipe.eval.call_args_list[1].args[2]
        second_daily_key = pipe.eval.call_args_list[1].args[3]

        assert first_minute_key == second_minute_key
        assert first_daily_key == second_daily_key

    @pytest.mark.asyncio
    async def test_different_keys_have_independent_redis_budgets(self, monkeypatch):
        """Verify that two distinct keys get different Redis keys."""
        connection, pipe = self._setup_mock_connection(
            allowed=1, minute_count=1, daily_count=1
        )
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=connection),
        )

        service = RedisService()
        key_1 = uuid4()
        key_2 = uuid4()

        await service.check_rate_limit(key_1)
        k1_minute = pipe.eval.call_args_list[0].args[2]
        k1_daily = pipe.eval.call_args_list[0].args[3]

        await service.check_rate_limit(key_2)
        k2_minute = pipe.eval.call_args_list[1].args[2]
        k2_daily = pipe.eval.call_args_list[1].args[3]

        assert k1_minute != k2_minute
        assert k1_daily != k2_daily
        assert str(key_1) in k1_minute
        assert str(key_2) in k2_minute

    @pytest.mark.asyncio
    async def test_different_keys_same_organization_have_independent_budgets(
        self, monkeypatch
    ):
        """Verify that two distinct API keys for the same organization have independent Redis budgets."""
        connection, pipe = self._setup_mock_connection(
            allowed=1, minute_count=1, daily_count=1
        )
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
        k1_minute = pipe.eval.call_args_list[0].args[2]
        k1_daily = pipe.eval.call_args_list[0].args[3]

        await service.check_rate_limit(key_dto_2.id)
        k2_minute = pipe.eval.call_args_list[1].args[2]
        k2_daily = pipe.eval.call_args_list[1].args[3]

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

    @pytest.mark.asyncio
    async def test_429_minute_exceeded_does_not_increment_daily_counter(
        self, monkeypatch, sample_api_key_dto, caplog
    ):
        """Verify that when minute quota is exceeded (429), the daily counter is NOT incremented."""
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 2)
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_DAY", 100)

        in_memory_conn = InMemoryRateLimitConnection(minute_limit=2, daily_limit=100)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=in_memory_conn),
        )

        service = RedisService()

        # Request 1: allowed
        allowed1, info1 = await service.check_rate_limit(sample_api_key_dto.id)
        assert allowed1 is True
        assert info1.remaining_minute == 1
        assert info1.remaining_daily == 99

        # Request 2: allowed (reaches minute limit of 2)
        allowed2, info2 = await service.check_rate_limit(sample_api_key_dto.id)
        assert allowed2 is True
        assert info2.remaining_minute == 0
        assert info2.remaining_daily == 98

        # Request 3: rejected (minute quota exceeded -> 429)
        with caplog.at_level(logging.WARNING):
            allowed3, info3 = await service.check_rate_limit(sample_api_key_dto.id)
        assert allowed3 is False
        assert info3.limit_exceeded is True
        assert info3.remaining_minute == 0
        # Daily remaining must NOT have decreased!
        assert info3.remaining_daily == 98

        # Request 4: rejected again
        allowed4, info4 = await service.check_rate_limit(sample_api_key_dto.id)
        assert allowed4 is False
        assert info4.remaining_daily == 98

        # Verify daily counter in store did not increment beyond 2
        daily_keys = [k for k in in_memory_conn.counters if "rate_limit:daily:" in k]
        assert len(daily_keys) == 1
        assert in_memory_conn.counters[daily_keys[0]] == 2

        # Verify log warning has UUID and no secrets
        assert str(sample_api_key_dto.id) in caplog.text
        assert sample_api_key_dto.prefix not in caplog.text
        assert sample_api_key_dto.key_hash not in caplog.text

    @pytest.mark.asyncio
    async def test_daily_window_limit_enforced_without_incrementing_counters(
        self, monkeypatch, sample_api_key_dto
    ):
        """Verify that when daily quota is exceeded, counters are not incremented further."""
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 100)
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_DAY", 3)

        in_memory_conn = InMemoryRateLimitConnection(minute_limit=100, daily_limit=3)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=in_memory_conn),
        )

        service = RedisService()

        # 3 allowed requests
        for _ in range(3):
            allowed, _ = await service.check_rate_limit(sample_api_key_dto.id)
            assert allowed is True

        # 4th request: daily quota reached
        allowed4, info4 = await service.check_rate_limit(sample_api_key_dto.id)
        assert allowed4 is False
        assert info4.limit_exceeded is True
        assert info4.remaining_daily == 0

        # Check counters remain at 3
        daily_keys = [k for k in in_memory_conn.counters if "rate_limit:daily:" in k]
        minute_keys = [k for k in in_memory_conn.counters if "rate_limit:minute:" in k]
        assert in_memory_conn.counters[daily_keys[0]] == 3
        assert in_memory_conn.counters[minute_keys[0]] == 3

    @pytest.mark.asyncio
    async def test_concurrent_requests_share_and_respect_quota_limits_without_burning_daily(
        self, monkeypatch, sample_api_key_dto
    ):
        """Verify concurrent requests respect minute limits without burning daily quota."""
        minute_limit = 3
        daily_limit = 100
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", minute_limit)
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_DAY", daily_limit)

        in_memory_conn = InMemoryRateLimitConnection(
            minute_limit=minute_limit, daily_limit=daily_limit
        )
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=in_memory_conn),
        )

        service = RedisService()
        # Fire 10 concurrent requests
        results = await asyncio.gather(
            *[service.check_rate_limit(sample_api_key_dto.id) for _ in range(10)]
        )

        allowed_count = sum(1 for is_allowed, _ in results if is_allowed)
        rejected_count = sum(1 for is_allowed, _ in results if not is_allowed)

        assert allowed_count == 3
        assert rejected_count == 7

        # Daily counter must be exactly 3, not 10!
        daily_keys = [k for k in in_memory_conn.counters if "rate_limit:daily:" in k]
        assert in_memory_conn.counters[daily_keys[0]] == 3

    @pytest.mark.asyncio
    async def test_check_rate_limit_rejects_raw_api_key_string(self):
        """Verify check_rate_limit immediately rejects non-UUID strings with ValueError."""
        service = RedisService()

        with pytest.raises(ValueError, match="key_id must be a valid UUID"):
            await service.check_rate_limit("dia_dev_v1_some_secret_key")

        with pytest.raises(ValueError, match="key_id must be a valid UUID"):
            await service.check_rate_limit("not-a-uuid")


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

    def test_api_key_without_organization_fails_401_without_redis_call(
        self, monkeypatch, client_with_api_key_standard, mock_redis_service
    ):
        """Verify that an API key without organization is rejected with 401 without any Redis call (AC-4)."""
        from document_ia_api.api import auth as auth_mod

        key_no_org_dto = ApiKeyDTO(
            id=uuid4(),
            organization_id=uuid4(),
            organization=None,
            key_hash="hash",
            prefix="NOORGKEY",
            status=ApiKeyStatus.ACTIVE,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        async def fake_get(self, presented: str):
            return key_no_org_dto

        monkeypatch.setattr(
            auth_mod.ApiKeyService,
            "get_from_presented_key",
            fake_get,
        )

        response = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": "some-key-without-org"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "API key has no associated organization"
        mock_redis_service.check_rate_limit.assert_not_called()

    def test_multiple_accepted_presentations_of_same_key_share_quota(
        self, monkeypatch, client_with_api_key_standard
    ):
        """Verify multiple accepted presentations of the same API key share the same Redis quota and trigger 429."""
        from document_ia_api.api.middleware import rate_limiting_middleware as rl_mod

        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_MINUTE", 2)
        monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS_PER_DAY", 100)

        in_memory_conn = InMemoryRateLimitConnection(minute_limit=2, daily_limit=100)
        monkeypatch.setattr(
            "document_ia_api.infra.redis_service.redis_manager.get_connection",
            AsyncMock(return_value=in_memory_conn),
        )

        real_service = RedisService()
        monkeypatch.setattr(rl_mod, "redis_service", real_service)

        # Presentation 1 and Presentation 2 resolve to the same ApiKeyDTO in mock_api_key_service_auth fixture
        key_presentation_1 = "dia_dev_v1_pref_key1_chk"  # gitleaks:allow
        key_presentation_2 = "dia_prod_v2_pref_key2_chk"  # gitleaks:allow

        # Request 1 via presentation 1: allowed (1/2)
        resp1 = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": key_presentation_1}
        )
        assert resp1.status_code == 200
        assert resp1.headers["X-RateLimit-Remaining-Minute"] == "1"

        # Request 2 via presentation 2: allowed (2/2)
        resp2 = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": key_presentation_2}
        )
        assert resp2.status_code == 200
        assert resp2.headers["X-RateLimit-Remaining-Minute"] == "0"

        # Request 3 via presentation 1: rejected 429 (shared quota exceeded!)
        resp3 = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": key_presentation_1}
        )
        assert resp3.status_code == 429
        assert "Retry-After" in resp3.headers

        # Request 4 via presentation 2: rejected 429 as well
        resp4 = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": key_presentation_2}
        )
        assert resp4.status_code == 429
        assert "Retry-After" in resp4.headers

    def test_redis_outage_on_authenticated_route_returns_503(
        self, client_with_api_key_standard, standard_api_key_value, mock_redis_service
    ):
        """Verify that Redis outage on an authenticated route returns 503 with Retry-After (AC-5)."""
        mock_redis_service.check_rate_limit.side_effect = capacity_unavailable()

        response = client_with_api_key_standard.get(
            "/api/test", headers={"X-API-KEY": standard_api_key_value}
        )

        assert response.status_code == 503
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) > 0
