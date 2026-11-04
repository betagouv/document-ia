from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from redis.exceptions import RedisError

from document_ia_api.api.middleware.execution_admission import check_execution_admission
from document_ia_api.api.middleware.rate_limiting_middleware import check_rate_limit
from document_ia_api.infra.redis_service import RedisService
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_infra.redis.admission import AdmissionUnavailableError
from document_ia_infra.redis.redis_settings import RedisSettings


@pytest.fixture
async def organization_id():
    return uuid4()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [None, RedisError("down"), RuntimeError("unexpected")]
)
async def test_quota_check_fails_closed(monkeypatch, failure):
    get_connection = AsyncMock(return_value=None)
    if failure is not None:
        get_connection.side_effect = failure
    monkeypatch.setattr(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        get_connection,
    )
    with pytest.raises(HTTPException) as exc:
        await RedisService().check_rate_limit("test-key")
    assert exc.value.status_code == 503
    assert int(exc.value.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_quota_pipeline_failure_is_not_client_exhaustion(monkeypatch):
    connection = MagicMock()
    pipe = AsyncMock()
    connection.pipeline.return_value.__aenter__.return_value = pipe
    pipe.execute.side_effect = RedisError("write failed")
    monkeypatch.setattr(
        "document_ia_api.infra.redis_service.redis_manager.get_connection",
        AsyncMock(return_value=connection),
    )
    with pytest.raises(HTTPException) as exc:
        await RedisService().check_rate_limit("test-key")
    pipe.execute.assert_awaited_once()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("daily", [False, True])
async def test_client_quota_returns_429_and_correct_retry_window(monkeypatch, daily):
    reset = datetime.now() + timedelta(seconds=3600 if daily else 30)
    info = RateLimitInfo(
        limit_exceeded=True,
        remaining_minute=1 if daily else 0,
        remaining_daily=0 if daily else 1,
        reset_minute=None if daily else reset.isoformat(),
        reset_daily=reset.isoformat() if daily else None,
    )
    monkeypatch.setattr(
        "document_ia_api.api.middleware.rate_limiting_middleware.redis_service.check_rate_limit",
        AsyncMock(return_value=(False, info)),
    )
    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(SimpleNamespace(state=SimpleNamespace()), "test-key")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) == (3600 if daily else 30)


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("suffix", ["execute", "execute-sync"])
def test_all_execution_routes_refuse_before_creating_resources(
    monkeypatch, client_with_api_key_standard, standard_api_key_value, version, suffix
):
    client = client_with_api_key_standard
    client.app.dependency_overrides.pop(check_execution_admission)
    connection = MagicMock()
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.redis_manager.get_connection",
        AsyncMock(return_value=connection),
    )
    check = AsyncMock(side_effect=AdmissionUnavailableError("full"))
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.admit_execution", check
    )
    service = (
        "workflow_service.WorkflowService"
        if version == "v1"
        else "workflow_v2_service.WorkflowV2Service"
    )
    execute = AsyncMock(side_effect=AssertionError("Execution must not start"))
    monkeypatch.setattr(
        f"document_ia_api.application.services.{service}.execute_workflow", execute
    )
    response = client.post(
        f"/api/{version}/workflows/example/{suffix}",
        data={"file_url": "https://example.com/test.pdf"},
        headers={"X-API-KEY": standard_api_key_value},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "http.service_unavailable"
    assert response.json()["errors"]["error"] == "execution_capacity_unavailable"
    assert int(response.headers["Retry-After"]) > 0
    check.assert_awaited_once_with(connection)
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_connection_failure_and_recovery(monkeypatch):
    get = AsyncMock(side_effect=[None, MagicMock()])
    check = AsyncMock()
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.redis_manager.get_connection",
        get,
    )
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.admit_execution", check
    )
    with pytest.raises(HTTPException) as exc:
        await check_execution_admission()
    assert exc.value.status_code == 503
    check.assert_not_awaited()
    await check_execution_admission()
    check.assert_awaited_once()


def test_result_reads_do_not_depend_on_redis(
    monkeypatch, client_with_api_key_standard, standard_api_key_value, organization_id
):
    client = client_with_api_key_standard
    client.app.dependency_overrides.pop(check_execution_admission)
    get = AsyncMock(side_effect=AssertionError("Result reads must not use Redis"))
    monkeypatch.setattr(
        "document_ia_api.api.middleware.execution_admission.redis_manager.get_connection",
        get,
    )
    event = SimpleNamespace(
        organization_id=organization_id, event={"version": 1}, workflow_id="example"
    )
    monkeypatch.setattr(
        "document_ia_api.api.routes.v1.executions.EventStoreService.get_last_event_for_execution_id",
        AsyncMock(return_value=event),
    )
    monkeypatch.setattr(
        "document_ia_api.api.routes.v1.executions.workflow_repository.get_workflow_by_id",
        AsyncMock(return_value={"id": "example"}),
    )
    monkeypatch.setattr(
        "document_ia_api.api.routes.v1.executions.ExecutionService.get_event_model",
        lambda *args: {
            "id": "existing",
            "status": "FAILED",
            "data": {
                "error_type": "test",
                "failed_step": None,
                "retry_count": 0,
                "workflow_id": "example",
                "error_message": "already completed",
            },
        },
    )
    response = client.get(
        "/api/v1/executions/existing", headers={"X-API-KEY": standard_api_key_value}
    )
    assert response.status_code == 200
    assert response.json()["id"] == "existing"
    get.assert_not_awaited()


def test_password_url_uses_real_secret_and_escapes_reserved_characters():
    settings = RedisSettings(
        REDIS_URL=None, REDIS_PASSWORD=SecretStr("test@/:password")
    )
    assert settings.get_redis_url().startswith("redis://:test%40%2F%3Apassword@")
