import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from document_ia_worker.core.ocr import base_http_ocr_service as base_module
from document_ia_worker.core.ocr.mistral.mistral_http_ocr_service import (
    MistralHttpOcrService,
)
from document_ia_worker.core.ocr.mistral.mistral_ocr_settings import MistralOcrSettings


@pytest.fixture
def ocr_service():
    return MistralHttpOcrService(
        config=MistralOcrSettings(
            OPENAI_API_KEY=SecretStr("test-credential-do-not-log"),
            OPENAI_BASE_URL="https://ocr.invalid/v1",
        )
    )


def install_transport(monkeypatch, handler):
    client_class = httpx.AsyncClient
    created_clients = []

    def client(**kwargs):
        instance = client_class(transport=httpx.MockTransport(handler), **kwargs)
        created_clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return created_clients


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["timeout", "unauthorized", "forbidden", "malformed"]
)
async def test_failure_logs_safe_diagnostics(
    failure, ocr_service, monkeypatch, tmp_path, caplog
):
    document = tmp_path / "private-document.pdf"
    document.write_bytes(b"private-document-content")
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(
                "test-credential-do-not-log private-document-content https://ocr.invalid",
                request=request,
            )
        if failure == "unauthorized":
            return httpx.Response(401, text="private-response-content")
        if failure == "forbidden":
            return httpx.Response(403, text="private-response-content")
        return httpx.Response(200, text="private-response-content")

    clients = install_transport(monkeypatch, handler)
    clock = iter([100.0, 160.0])
    monkeypatch.setattr(
        base_module, "time", SimpleNamespace(perf_counter=lambda: next(clock))
    )
    with caplog.at_level(logging.ERROR, logger=base_module.__name__):
        result = await ocr_service.extract_text_from_image(
            str(document), "application/pdf"
        )

    assert len(clients) == 1
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-credential-do-not-log"
    assert result.success is False
    assert result.content == ""
    message = caplog.text
    expected_exception, expected_status = {
        "timeout": ("ReadTimeout", None),
        "unauthorized": ("HTTPStatusError", 401),
        "forbidden": ("HTTPStatusError", 403),
        "malformed": ("ValidationError", None),
    }[failure]
    assert f"exception={expected_exception}" in message
    assert "elapsed_seconds=60.000" in message
    assert f"status_code={expected_status}" in message
    assert "base_http_ocr_service.py:" in message
    assert "extract_text_from_image" in message
    assert "mistral_http_ocr_service.py:" in message
    for private in (
        "test-credential-do-not-log",
        "private-document-content",
        "private-response-content",
        "private-document.pdf",
        "https://ocr.invalid",
        "Authorization",
    ):
        assert private not in message


@pytest.mark.asyncio
async def test_missing_api_key_fails_locally_without_http_request(
    monkeypatch, tmp_path, caplog
):
    document = tmp_path / "document.pdf"
    document.write_bytes(b"test-pdf")
    service = MistralHttpOcrService(
        config=MistralOcrSettings(
            OPENAI_API_KEY=None,
            OPENAI_BASE_URL="https://ocr.invalid/v1",
        )
    )
    requests = []
    clients = install_transport(
        monkeypatch, lambda request: requests.append(request) or httpx.Response(200)
    )

    with caplog.at_level(logging.ERROR, logger=base_module.__name__):
        result = await service.extract_text_from_image(str(document), "application/pdf")

    assert len(clients) == 1
    assert len(requests) == 0
    assert result.success is False
    assert result.content == ""
    assert "exception=HTTPOCRMissConfigurationException" in caplog.text
    assert "status_code=None" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_callable_api_key_override_sends_request_and_logs_http_status(
    status, ocr_service, monkeypatch, tmp_path, caplog
):
    document = tmp_path / "document.pdf"
    document.write_bytes(b"test-pdf")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="unauthorized")

    clients = install_transport(monkeypatch, handler)
    monkeypatch.setattr(ocr_service, "get_api_key", lambda: "invalid-key-for-test")

    with caplog.at_level(logging.ERROR, logger=base_module.__name__):
        result = await ocr_service.extract_text_from_image(
            str(document), "application/pdf"
        )

    assert len(clients) == 1
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer invalid-key-for-test"
    assert result.success is False
    assert result.content == ""
    assert "exception=HTTPStatusError" in caplog.text
    assert f"status_code={status}" in caplog.text


@pytest.mark.asyncio
async def test_successful_request_still_parses_response(
    ocr_service, monkeypatch, tmp_path, caplog
):
    document = tmp_path / "document.pdf"
    document.write_bytes(b"test-pdf")

    def handler(request):
        assert request.url.path == "/v1/ocr"
        assert request.extensions["timeout"] == {
            "connect": 60,
            "read": 60,
            "write": 60,
            "pool": 60,
        }
        return httpx.Response(
            200,
            json={
                "pages": [{"index": 0, "markdown": "recognized text", "tables": []}],
                "model": "mistral-ocr-2512",
            },
        )

    clients = install_transport(monkeypatch, handler)
    result = await ocr_service.extract_text_from_image(str(document), "application/pdf")
    assert len(clients) == 1
    assert result.success is True
    assert "recognized text" in result.content
    assert "HTTP OCR call failed" not in caplog.text


@pytest.mark.asyncio
async def test_custom_timeout_extends_budget_without_changing_connect(
    ocr_service, monkeypatch, tmp_path
):
    document = tmp_path / "document.pdf"
    document.write_bytes(b"test-pdf")
    service = MistralHttpOcrService(config=ocr_service.config, timeout=120)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.extensions["timeout"] == {
            "connect": 60,
            "read": 120,
            "write": 120,
            "pool": 120,
        }
        return httpx.Response(
            200,
            json={
                "pages": [{"index": 0, "markdown": "recognized text", "tables": []}],
                "model": "mistral-ocr-2512",
            },
        )

    clients = install_transport(monkeypatch, handler)
    result = await service.extract_text_from_image(str(document), "application/pdf")
    assert len(clients) == 1
    assert len(requests) == 1
    assert result.success is True
    assert "recognized text" in result.content
