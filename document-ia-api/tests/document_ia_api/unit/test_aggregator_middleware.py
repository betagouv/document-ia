from __future__ import annotations

import json
import logging
from typing import Annotated, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response

from document_ia_api.api.middleware.aggregator_middleware import (
    AggregationMiddleware,
    _unwrap_is_secret_type,
    _wrap_response_and_capture,
    get_request_payload_safely,
)
from document_ia_infra.core.model.types.secret import (
    SecretPayloadBytes,
    SecretPayloadStr,
)


def test_unwrap_is_secret_type_variants():
    assert _unwrap_is_secret_type(SecretPayloadStr)
    assert _unwrap_is_secret_type(Optional[SecretPayloadStr])
    assert _unwrap_is_secret_type(Annotated[SecretPayloadStr, Field(description="x")])
    assert _unwrap_is_secret_type(SecretPayloadBytes)

    class NotSecret(BaseModel):
        x: int

    assert _unwrap_is_secret_type(NotSecret) is False


@pytest.mark.asyncio
async def test_wrap_response_and_capture_strict_allowlist():
    raw_response = JSONResponse(
        content={"data": "test_output", "secret": "SUPER_SECRET_123"},
        status_code=200,
        headers={
            "X-Request-Id": "req-999",
            "Idempotent-Replay": "true",
            "Set-Cookie": "session=secret_token",
            "X-Internal-Token": "secret_internal",
        },
    )

    request = MagicMock(spec=Request)
    returned_resp, meta = await _wrap_response_and_capture(request, raw_response)

    # Status and response object
    assert returned_resp.status_code == 200
    assert meta["status_code"] == 200

    # Headers allowlist check: allowed headers kept, sensitive headers pruned
    headers = meta["response_headers"]
    assert "x-request-id" in headers
    assert "idempotent-replay" in headers
    assert "content-type" in headers
    assert "set-cookie" not in headers
    assert "x-internal-token" not in headers

    # Envelope metrics check
    assert "response_body" in meta
    assert meta["response_body"]["bytes"] > 0
    assert "application/json" in meta["response_body"]["content_type"]

    # Zero body preview
    assert "body_preview" not in meta
    assert "response_body_preview" not in meta


@pytest.mark.asyncio
async def test_get_request_payload_safely_masks_and_filters():
    request = MagicMock(spec=Request)
    request.query_params = {
        "limit": "20",
        "api_key": "SECRET_KEY_abc123",  # gitleaks:allow
        "unknown_query": "sensitive_data",
    }
    request.path_params = {
        "execution_id": "exec-456",
        "unauthorized_path_param": "leaked_param",
    }
    request.headers = Headers(
        {
            "content-type": "application/json",
            "content-length": "42",
            "authorization": "Bearer secret_bearer_token",
        }
    )
    request.state = MagicMock()

    await get_request_payload_safely(request)

    payload = request.state.aggregator_payload
    assert payload is not None

    # Query params: allowed kept, unknown masked
    assert payload["query_params"]["limit"] == "20"
    assert payload["query_params"]["api_key"] == "**********"
    assert payload["query_params"]["unknown_query"] == "**********"

    # Path params: only allowed keys retained
    assert payload["path_params"]["execution_id"] == "exec-456"
    assert "unauthorized_path_param" not in payload["path_params"]

    # Request body metric
    assert payload["request_body"]["content_type"] == "application/json"
    assert payload["request_body"]["bytes"] == 42

    # Zero body preview
    assert "body_preview" not in payload
    assert "request_body_preview" not in payload


@pytest.mark.asyncio
async def test_aggregation_middleware_zero_body_preview_in_entry(monkeypatch):
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

    request = MagicMock(spec=Request)
    request.method = "POST"
    request.url.path = "/api/v1/workflows/wf-1/execute"
    request.client.host = "127.0.0.1"
    request.headers = Headers(
        {
            "content-type": "application/json",
            "x-request-id": "req-100",
            "authorization": "Bearer SECRET_JWT_TOKEN",
            "cookie": "session_id=SECRET_COOKIE",
            "x-custom-header": "SECRET_HEADER",
        }
    )
    request.query_params = {
        "limit": "10",
        "token": "SECRET_TOKEN_IN_QUERY",
    }
    request.path_params = {
        "workflow_id": "wf-1",
        "internal_id": "INTERNAL_SECRET",
    }
    request.scope = {"route": MagicMock(path="/api/v1/workflows/{workflow_id}/execute")}
    request.state = MagicMock()
    request.state.request_id = "req-100"
    request.state.organization = MagicMock(id="org-1")

    # Dependency captured payload
    await get_request_payload_safely(request)

    # Next endpoint call returns a response with sensitive data in body
    secret_body_marker = "SECRET_SYNTHETIC_MARKER_9999"  # gitleaks:allow

    async def call_next(req: Request) -> Response:
        return JSONResponse(
            content={"message": "ok", "secret": secret_body_marker},
            status_code=201,
            headers={
                "X-Request-Id": "req-100",
                "Set-Cookie": "sensitive_cookie=value",
            },
        )

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 201

    assert len(logged_entries) == 1
    entry = logged_entries[0]

    # Verify no raw body previews exist anywhere in the entry
    assert "request_body_preview" not in entry
    assert "response_body_preview" not in entry
    assert "body_preview" not in entry

    # Verify sensitive marker is NEVER present in serialized entry
    entry_json_str = json.dumps(entry)
    assert secret_body_marker not in entry_json_str
    assert "SECRET_JWT_TOKEN" not in entry_json_str
    assert "SECRET_COOKIE" not in entry_json_str
    assert "SECRET_HEADER" not in entry_json_str
    assert "SECRET_TOKEN_IN_QUERY" not in entry_json_str
    assert "INTERNAL_SECRET" not in entry_json_str

    # Verify allowed metadata is correctly logged
    assert entry["request_id"] == "req-100"
    assert entry["method"] == "POST"
    assert entry["headers"] == {
        "content-type": "application/json",
        "x-request-id": "req-100",
    }
    assert entry["query_params"]["limit"] == "10"
    assert entry["query_params"]["token"] == "**********"
    assert entry["path_params"] == {"workflow_id": "wf-1"}
    assert entry["request_body"]["content_type"] == "application/json"
    assert entry["response_body"]["bytes"] > 0
