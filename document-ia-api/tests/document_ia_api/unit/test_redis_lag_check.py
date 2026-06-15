import pytest
from unittest.mock import AsyncMock, patch
from redis.exceptions import ResponseError

from document_ia_api.infra.redis_service import redis_service
from document_ia_infra.redis.redis_settings import redis_settings


@pytest.mark.asyncio
async def test_check_event_stream_lag_success():
    # Mock redis_manager.get_connection
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups = AsyncMock(
        return_value=[
            {"name": "other_group", "lag": 5, "pending": 1},
            {"name": redis_settings.EVENT_CONSUMER_GROUP, "lag": 3, "pending": 2},
        ]
    )

    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=mock_redis,
    ):
        lag, pending = await redis_service.check_event_stream_lag()
        assert lag == 3
        assert pending == 2
        mock_redis.xinfo_groups.assert_called_once_with(
            redis_settings.EVENT_STREAM_NAME
        )


@pytest.mark.asyncio
async def test_check_event_stream_lag_group_not_found_fallback():
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups = AsyncMock(
        return_value=[{"name": "other_group", "lag": 5, "pending": 1}]
    )
    mock_redis.xlen = AsyncMock(return_value=12)

    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=mock_redis,
    ):
        lag, pending = await redis_service.check_event_stream_lag()
        assert lag == 12
        assert pending == 0
        mock_redis.xlen.assert_called_once_with(redis_settings.EVENT_STREAM_NAME)


@pytest.mark.asyncio
async def test_check_event_stream_lag_no_such_key():
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups = AsyncMock(side_effect=ResponseError("no such key"))

    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=mock_redis,
    ):
        lag, pending = await redis_service.check_event_stream_lag()
        assert lag == 0
        assert pending == 0


@pytest.mark.asyncio
async def test_check_event_stream_lag_no_such_group():
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups = AsyncMock(side_effect=ResponseError("no such group"))
    mock_redis.xlen = AsyncMock(return_value=7)

    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=mock_redis,
    ):
        lag, pending = await redis_service.check_event_stream_lag()
        assert lag == 7
        assert pending == 0
        mock_redis.xlen.assert_called_once_with(redis_settings.EVENT_STREAM_NAME)


@pytest.mark.asyncio
async def test_check_event_stream_lag_redis_unavailable():
    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=None,
    ):
        lag, pending = await redis_service.check_event_stream_lag()
        assert lag is None
        assert pending is None


@pytest.mark.asyncio
async def test_check_connectivity_populates_nb_execution_to_process():
    mock_redis = AsyncMock()
    mock_redis.xinfo_groups = AsyncMock(
        return_value=[
            {"name": redis_settings.EVENT_CONSUMER_GROUP, "lag": 42, "pending": 8},
        ]
    )

    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=mock_redis,
    ):
        status = await redis_service.check_connectivity()
        assert status.connected is True
        assert status.is_healthy is True
        assert status.nb_execution_undelivered == 42
        assert status.nb_execution_being_processed == 8
        assert status.nb_execution_to_process == 50


@pytest.mark.asyncio
async def test_check_connectivity_redis_unavailable():
    with patch(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        return_value=None,
    ):
        status = await redis_service.check_connectivity()
        assert status.connected is False
        assert status.is_healthy is False
        assert status.nb_execution_undelivered is None
        assert status.nb_execution_being_processed is None
        assert status.nb_execution_to_process is None
