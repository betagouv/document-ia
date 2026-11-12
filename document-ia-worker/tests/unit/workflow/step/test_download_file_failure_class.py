"""Download failures must keep their delivery classification after sanitization.

The safe-logging change replaces raw httpx errors with a sanitized exception so
no signed URL reaches the logs. That must not cost the failure class that
`classify_failure` uses for delivery metrics and retained DLQ entries.
"""

from datetime import datetime
from uuid import uuid4

import httpx
import pytest

from document_ia_infra.redis.failure_classification import classify_failure
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)

SECRET_QUERY = "X-Amz-Signature=SECRET_SIGNATURE_1234"
FILE_URL = f"https://example.com/private/invoice.pdf?{SECRET_QUERY}"


@pytest.fixture
def context() -> MainWorkflowContext:
    return MainWorkflowContext(
        execution_id=str(uuid4()),
        organization_id=uuid4(),
        workflow_version=1,
        start_time=datetime.now(),
        steps_metadata=[],
    )


def _step(context: MainWorkflowContext, handler) -> DownloadFileStep:
    return DownloadFileStep(
        main_workflow_context=context,
        file_url=FILE_URL,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (404, "permanent"),
        (401, "permanent"),
        (429, "temporary"),
        (503, "temporary"),
    ],
)
async def test_http_status_failure_keeps_classification(
    context: MainWorkflowContext, status: int, expected: str
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status, request=request)

    step = _step(context, handler)
    await step._prepare_step()
    try:
        with pytest.raises(Exception) as excinfo:
            await step._handle_file_url(FILE_URL)
    finally:
        await step.cleanup(is_last_cleanup=True)

    assert classify_failure(excinfo.value) == expected
    # Sanitization is still enforced: no signed URL or signature in the message.
    assert SECRET_QUERY not in str(excinfo.value)
    assert "private/invoice.pdf" not in str(excinfo.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("connect timed out"),
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
async def test_transport_failure_keeps_temporary_classification(
    context: MainWorkflowContext, error: httpx.TransportError
):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    step = _step(context, handler)
    await step._prepare_step()
    try:
        with pytest.raises(Exception) as excinfo:
            await step._handle_file_url(FILE_URL)
    finally:
        await step.cleanup(is_last_cleanup=True)

    assert classify_failure(excinfo.value) == "temporary"
    assert SECRET_QUERY not in str(excinfo.value)


@pytest.mark.asyncio
async def test_sanitized_exception_does_not_retain_raw_error_text(
    context: MainWorkflowContext,
):
    """The sanitized exception must not carry the raw httpx error as a cause."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404, request=request)

    step = _step(context, handler)
    await step._prepare_step()
    try:
        with pytest.raises(Exception) as excinfo:
            await step._handle_file_url(FILE_URL)
    finally:
        await step.cleanup(is_last_cleanup=True)

    raised = excinfo.value
    assert raised.__cause__ is None
    assert raised.__context__ is None or SECRET_QUERY not in str(raised.__context__)
