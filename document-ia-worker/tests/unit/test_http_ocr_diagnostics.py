import logging

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

    def client(**kwargs):
        return client_class(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "unauthorized", "malformed"])
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
        return httpx.Response(200, text="private-response-content")

    install_transport(monkeypatch, handler)
    clock = iter([100.0, 160.0])
    monkeypatch.setattr(base_module, "monotonic", lambda: next(clock))
    with caplog.at_level(logging.ERROR, logger=base_module.__name__):
        result = await ocr_service.extract_text_from_image(
            str(document), "application/pdf"
        )

    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-credential-do-not-log"
    assert result.success is False
    assert result.content == ""
    message = caplog.text
    expected = {
        "timeout": "ReadTimeout",
        "unauthorized": "HTTPStatusError",
        "malformed": "ValidationError",
    }[failure]
    assert f"exception={expected}" in message
    assert "elapsed_seconds=60.000" in message
    assert (
        "status_code=401" in message
        if failure == "unauthorized"
        else "status_code=None" in message
    )
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

    install_transport(monkeypatch, handler)
    result = await ocr_service.extract_text_from_image(str(document), "application/pdf")
    assert result.success is True
    assert "recognized text" in result.content
    assert "HTTP OCR call failed" not in caplog.text


@pytest.mark.asyncio
async def test_live_success_test_extends_timeout_without_changing_connect(
    ocr_service, monkeypatch
):
    import test_mistral_ocr_service as live_tests

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

    def service(**kwargs):
        return MistralHttpOcrService(config=ocr_service.config, **kwargs)

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(live_tests, "mistral_ocr_settings", ocr_service.config)
    monkeypatch.setattr(live_tests, "MistralHttpOcrService", service)
    await live_tests.test_extract_text_from_image_e2e_success()
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_live_unauthorized_test_requires_real_401(
    status, ocr_service, monkeypatch
):
    import test_mistral_ocr_service as live_tests

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="unauthorized")

    install_transport(monkeypatch, handler)
    monkeypatch.setattr(live_tests, "mistral_ocr_settings", ocr_service.config)
    monkeypatch.setattr(live_tests, "MistralHttpOcrService", lambda: ocr_service)
    if status == 401:
        await live_tests.test_extract_text_from_image_e2e_unauthorized(monkeypatch)
    else:
        with pytest.raises(AssertionError, match="Expected an HTTP 401"):
            await live_tests.test_extract_text_from_image_e2e_unauthorized(monkeypatch)
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer invalid-key-for-test"
