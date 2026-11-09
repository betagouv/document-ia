from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_worker.config.logging import setup_logging
from document_ia_worker.core.aggregator_log import (
    agg_buffer_var,
    execution_id_var,
    handle_finish_execution,
    start_time_var,
)
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepLLMMetadata,
)
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)


@pytest.fixture(autouse=True)
def configure_worker_logging():
    setup_logging()


@pytest.mark.asyncio
async def test_download_file_step_never_logs_full_url_or_query_parameters(caplog):
    context = MagicMock(spec=MainWorkflowContext)
    context.execution_id = str(uuid4())

    secret_signature = "SECRET_AWS_SIGNATURE_9999"
    secret_credential = "SECRET_AWS_CREDENTIAL_8888"
    sensitive_url = f"https://s3.fr-par.scw.cloud/private-bucket/secret_doc.pdf?X-Amz-Signature={secret_signature}&X-Amz-Credential={secret_credential}"

    step = DownloadFileStep(
        main_workflow_context=context,
        file_info=None,
        file_url=sensitive_url,
    )

    # Simulate network failure during download
    with caplog.at_level(logging.INFO):
        with pytest.raises(Exception):
            await step._handle_file_url(sensitive_url)

    logs = caplog.text

    # Safe host MUST be logged
    assert "s3.fr-par.scw.cloud" in logs

    # Full URL and sensitive query parameters MUST NEVER be logged
    assert secret_signature not in logs
    assert secret_credential not in logs
    assert sensitive_url not in logs
    assert "private-bucket" not in logs

    await step.cleanup(is_last_cleanup=True)


@pytest.mark.asyncio
async def test_download_file_step_never_logs_s3_key(caplog):
    context = MagicMock(spec=MainWorkflowContext)
    context.execution_id = str(uuid4())

    secret_s3_key = "sensitive/customer_path/SECRET_DOC_KEY_777.pdf"
    file_info = FileInfo(
        filename="secret_doc.pdf",
        s3_key=SecretStr(secret_s3_key),
        size=1024,
        content_type="application/pdf",
        uploaded_at="2026-11-09T10:00:00Z",
        presigned_url=SecretStr("https://s3.fr-par.scw.cloud/bucket/file?token=secret"),
    )

    step = DownloadFileStep(
        main_workflow_context=context,
        file_info=file_info,
    )

    with caplog.at_level(logging.INFO):
        await step._prepare_step()

    logs = caplog.text
    assert secret_s3_key not in logs

    await step.cleanup(is_last_cleanup=True)


def test_handle_finish_execution_purges_prompts_and_document_data(monkeypatch):
    logged_entries: list[dict] = []

    def mock_write(entry, tags):
        logged_entries.append(entry)

    monkeypatch.setattr(
        "document_ia_worker.core.aggregator_log.write_worker_aggregated_entry",
        mock_write,
    )

    token_eid = execution_id_var.set("exec-llm-789")
    token_buf = agg_buffer_var.set([])
    token_st = start_time_var.set(None)

    sens_user_prompt = "CONFIDENTIAL_USER_EXTRACTED_DOCUMENT_TEXT_SSN_12345"
    sens_system_prompt = "INTERNAL_SECRET_SYSTEM_PROMPT_INSTRUCTIONS"
    sens_image = "data:image/png;base64,SECRET_BASE64_IMAGE_STRING"

    llm_meta = StepLLMMetadata(
        step_name="llm_extraction_step",
        execution_time=2.45,
        request_tokens=150,
        response_tokens=75,
        model="gpt-4o",
        system_prompt=sens_system_prompt,
        user_prompt=sens_user_prompt,
        output_images=[sens_image],
    )

    test_logger = logging.getLogger("test_worker")
    handle_finish_execution(
        logger=test_logger,
        organization_id=uuid4(),
        workflow_id="wf-ocr-test",
        is_success=False,
        retry_count=1,
        workflow_steps=["download", "llm_extraction"],
        token_exec_id=token_eid,
        token_buf=token_buf,
        token_started_at=token_st,
        err_type="CustomExtractionError",
        err_message="Sensitive file content leaked in error message",
        failed_step="llm_extraction",
        workflow_metadata=[llm_meta],
    )

    assert len(logged_entries) == 1
    entry = logged_entries[0]

    # Check workflow metadata allowlist filtering
    assert len(entry["workflow_metadata"]) == 1
    step_meta = entry["workflow_metadata"][0]

    # Allowed fields MUST be present
    assert step_meta["step_name"] == "llm_extraction_step"
    assert step_meta["execution_time"] == 2.45
    assert step_meta["request_tokens"] == 150
    assert step_meta["response_tokens"] == 75
    assert step_meta["model"] == "gpt-4o"

    # Forbidden fields MUST be completely purged
    assert "user_prompt" not in step_meta
    assert "system_prompt" not in step_meta
    assert "output_images" not in step_meta

    # Serialized entry MUST NOT contain any sensitive prompt or document fragments
    entry_str = json.dumps(entry)
    assert sens_user_prompt not in entry_str
    assert sens_system_prompt not in entry_str
    assert sens_image not in entry_str

    # Error handling must not leak raw error_message
    assert entry["error_type"] == "CustomExtractionError"
    assert entry["failed_step"] == "llm_extraction"
    assert "error_message" not in entry
