from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from document_ia_api.api.contracts.api_key.api_key import APIKeyCreatedResult
from document_ia_api.api.contracts.webhook.webhook import (
    CreateWebHookRequest,
    WebHookResult,
)
from document_ia_api.api.middleware.aggregator_middleware import (
    AggregationMiddleware,
    get_request_payload_safely,
)
from document_ia_api.infra.webhook_notification_service import (
    WebhookNotificationService,
)
from document_ia_infra.core.model.types.secret import SecretDict
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.exception.retryable_exception import RetryableException


def test_api_key_created_result_masks_in_logs_and_clear_in_json():
    key_secret = "sk_live_SECRET_SYNTHETIC_API_KEY_98765"  # gitleaks:allow
    result = APIKeyCreatedResult(
        id=str(uuid4()),
        prefix="sk_live",
        status=ApiKeyStatus.ACTIVE,
        created_at="2026-11-09T10:00:00Z",
        updated_at="2026-11-09T10:00:00Z",
        key=SecretStr(key_secret),
    )

    # Logging representation (str/repr) MUST mask the secret
    str_repr = str(result)
    assert key_secret not in str_repr
    assert "**********" in str_repr

    # Legitimate client response (JSON dump) MUST deliver the clear secret key
    client_payload = result.model_dump(mode="json")
    assert client_payload["key"] == key_secret


def test_webhook_contracts_mask_headers_in_str_and_clear_in_json():
    auth_header = "Bearer SECRET_SYNTHETIC_WEBHOOK_TOKEN_123"
    request = CreateWebHookRequest(
        url="https://example.com/webhook",
        headers=SecretDict({"Authorization": auth_header}),
    )

    # String representation masks the header values
    assert auth_header not in str(request)
    assert auth_header not in repr(request)
    assert "***" in str(request)

    # JSON serialization preserves clear headers
    assert request.model_dump(mode="json")["headers"] == {"Authorization": auth_header}

    result = WebHookResult(
        id=str(uuid4()),
        organization_id=uuid4(),
        url="https://example.com/webhook",
        headers=SecretDict({"X-Secret": "CONFIDENTIAL"}),
        created_at="2026-11-09T10:00:00Z",
        updated_at="2026-11-09T10:00:00Z",
    )
    assert "CONFIDENTIAL" not in str(result)
    assert result.model_dump(mode="json")["headers"] == {"X-Secret": "CONFIDENTIAL"}


@pytest.mark.asyncio
async def test_safe_logging_under_various_payload_attacks(monkeypatch):
    """Verifies that synthetic secret markers injected through valid JSON, invalid corrupt JSON,
    multipart form, custom headers, or arbitrary query parameters NEVER leak into aggregator logs.
    """
    logged_entries: list[dict] = []

    mock_logger = MagicMock()
    mock_logger.info.side_effect = lambda msg, extra=None: logged_entries.append(
        json.loads(msg)
    )

    orig_get_logger = logging.getLogger

    def patched_get_logger(name=None):
        if name == "aggregator":
            return mock_logger
        return orig_get_logger(name)

    monkeypatch.setattr(
        "document_ia_api.api.middleware.aggregator_middleware.logging.getLogger",
        patched_get_logger,
    )

    app = MagicMock()
    middleware = AggregationMiddleware(app)

    SYNTH_SECRETS = [
        "SECRET_SYNTH_VALID_JSON_FIELD",
        "SECRET_SYNTH_CORRUPT_JSON_DATA",
        "SECRET_SYNTH_MULTIPART_FIELD",
        "SECRET_SYNTH_QUERY_PARAM",
        "SECRET_SYNTH_HEADER",
        "SECRET_SYNTH_RESPONSE_DATA",
    ]

    # 1. Test Valid JSON request with secret body and response
    req_valid_json = MagicMock(spec=Request)
    req_valid_json.method = "POST"
    req_valid_json.url.path = "/api/v1/extract"
    req_valid_json.client.host = "10.0.0.1"
    req_valid_json.headers = Headers(
        {
            "content-type": "application/json",
            "x-request-id": "req-1",
            "x-custom-secret": SYNTH_SECRETS[4],
        }
    )
    req_valid_json.query_params = {
        "limit": "10",
        "unauthorized_key": SYNTH_SECRETS[3],
    }
    req_valid_json.path_params = {"execution_id": "exec-1"}
    req_valid_json.scope = {"route": MagicMock(path="/api/v1/extract")}
    req_valid_json.state = MagicMock()
    req_valid_json.state.request_id = "req-1"

    body_bytes_1 = json.dumps({"secret_field": SYNTH_SECRETS[0]}).encode()
    req_valid_json.body = AsyncMock(return_value=body_bytes_1)

    await get_request_payload_safely(req_valid_json)

    async def call_next_1(_: Request) -> Response:
        return JSONResponse(
            content={"result": "done", "secret_resp": SYNTH_SECRETS[5]},
            status_code=200,
            headers={"Content-Type": "application/json", "X-Request-Id": "req-1"},
        )

    await middleware.dispatch(req_valid_json, call_next_1)

    # 2. Test Corrupt Invalid JSON request
    req_corrupt_json = MagicMock(spec=Request)
    req_corrupt_json.method = "POST"
    req_corrupt_json.url.path = "/api/v1/extract"
    req_corrupt_json.client.host = "10.0.0.1"
    req_corrupt_json.headers = Headers(
        {
            "content-type": "application/json",
            "x-request-id": "req-2",
        }
    )
    req_corrupt_json.query_params = {}
    req_corrupt_json.path_params = {}
    req_corrupt_json.scope = {"route": MagicMock(path="/api/v1/extract")}
    req_corrupt_json.state = MagicMock()
    req_corrupt_json.state.request_id = "req-2"

    corrupt_body = (
        f'{{"malformed": "{SYNTH_SECRETS[1]}", corrupted_unquoted_syntax'.encode()
    )
    req_corrupt_json.body = AsyncMock(return_value=corrupt_body)

    await get_request_payload_safely(req_corrupt_json)

    async def call_next_2(_: Request) -> Response:
        return JSONResponse(content={"error": "bad request"}, status_code=400)

    await middleware.dispatch(req_corrupt_json, call_next_2)

    # 3. Test Multipart request
    req_multipart = MagicMock(spec=Request)
    req_multipart.method = "POST"
    req_multipart.url.path = "/api/v1/upload"
    req_multipart.client.host = "10.0.0.1"
    req_multipart.headers = Headers(
        {
            "content-type": "multipart/form-data; boundary=---boundary",
            "x-request-id": "req-3",
        }
    )
    req_multipart.query_params = {}
    req_multipart.path_params = {}
    req_multipart.scope = {"route": MagicMock(path="/api/v1/upload")}
    req_multipart.state = MagicMock()
    req_multipart.state.request_id = "req-3"

    await get_request_payload_safely(req_multipart)

    async def call_next_3(_: Request) -> Response:
        return JSONResponse(content={"upload": "ok"}, status_code=201)

    await middleware.dispatch(req_multipart, call_next_3)

    assert len(logged_entries) == 3

    # CRITICAL INVARIANT: NONE of the synthetic secrets must appear in ANY serialized log entry
    for entry in logged_entries:
        entry_str = json.dumps(entry)
        for secret in SYNTH_SECRETS:
            assert secret not in entry_str, (
                f"Leak detected! Found {secret} in log entry: {entry_str}"
            )


@pytest.mark.asyncio
async def test_webhook_notification_service_sanitizes_urls_and_exceptions(caplog):
    secret_query = "AWSAccessKeyId=SECRET_KEY_123&Signature=SECRET_SIG_456"
    sensitive_webhook_url = f"https://api.external-partner.com/webhook?{secret_query}"

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    webhook_dto = WebHookDTO(
        id=uuid4(),
        organization_id=uuid4(),
        url=sensitive_webhook_url,
        headers={"X-Secret-Auth": "SUPER_SECRET_VALUE"},
        created_at=now,
        updated_at=now,
    )

    event_dto = MagicMock(spec=EventDTO)
    event_dto.execution_id = "exec-999"

    mock_client = AsyncMock()
    mock_client.is_closed = False
    service = WebhookNotificationService(
        http_client=mock_client, retry_initial_delay_seconds=0.01
    )
    service._execution_service = MagicMock()
    service._execution_service.get_event_model.return_value = MagicMock(
        model_dump_json=lambda: "{}"
    )

    # Case 1: Success call
    mock_resp_success = MagicMock(status_code=200)
    mock_resp_success.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_resp_success
    service._http_client = mock_client

    with caplog.at_level(logging.INFO):
        await service._call_webhook_notification(webhook_dto, event_dto)

    # Check logs: zero secret query or complete URL or custom secret headers
    log_text = caplog.text
    assert "Sending webhook notification" in log_text
    assert secret_query not in log_text
    assert "SUPER_SECRET_VALUE" not in log_text

    caplog.clear()

    # Case 2: HTTP error (e.g. 500)
    mock_resp_error = MagicMock(status_code=500)
    mock_resp_error.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(url=httpx.URL(sensitive_webhook_url)),
        response=mock_resp_error,
    )
    mock_client.post.return_value = mock_resp_error

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RetryableException):
            await service._deliver_webhook_with_retry_policy(webhook_dto, event_dto)

    error_logs = caplog.text
    assert "Retryable webhook HTTP status 500" in error_logs
    assert secret_query not in error_logs
    assert "SECRET_KEY_123" not in error_logs


@pytest.mark.asyncio
async def test_fastapi_validation_error_on_corrupt_json_and_invalid_payload_never_leaks_secrets(
    caplog,
):
    from document_ia_api.api.exceptions.handler.exception_handlers import (
        setup_exception_handlers,
    )
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    test_app = FastAPI()
    setup_exception_handlers(test_app)

    @test_app.post("/test-validation")
    async def endpoint_with_validation(req: CreateWebHookRequest):
        return {"status": "ok"}

    # Test OpenAPI schema validity - no broken refs
    openapi_schema = test_app.openapi()
    assert openapi_schema is not None
    schema_str = json.dumps(openapi_schema)
    assert "CreateWebHookRequest" in schema_str
    # Ensure there is no orphaned ref ending with __1
    assert "CreateWebHookRequest-Input__1" not in schema_str

    synth_secret = "SUPER_SECRET_PAYLOAD_VALUE_9999"  # gitleaks:allow

    # 1. Invalid payload that fails Pydantic validation
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        with caplog.at_level(logging.WARNING):
            resp = await client.post(
                "/test-validation",
                json={
                    "url": "https://example.com/webhook",
                    "headers": {"secret_key": [1, 2, 3]},  # Invalid type for headers
                    "leak_marker": synth_secret,
                },
            )
            assert resp.status_code == 422
            # The synth secret must never appear in any log output
            assert synth_secret not in caplog.text
            assert "Validation error on /test-validation" in caplog.text

    caplog.clear()

    # 2. Corrupt raw JSON containing secret marker
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        with caplog.at_level(logging.WARNING):
            resp = await client.post(
                "/test-validation",
                content=f'{{"secret": "{synth_secret}", broken_unquoted'.encode(),
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code == 422
            assert synth_secret not in caplog.text
