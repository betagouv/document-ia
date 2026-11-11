import logging
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)


@pytest.fixture
def mock_context() -> MainWorkflowContext:
    return MainWorkflowContext(
        execution_id=str(uuid4()),
        organization_id=uuid4(),
        workflow_version=1,
        start_time=datetime.now(),
        steps_metadata=[],
    )


@pytest.fixture
def sample_file_info() -> FileInfo:
    return FileInfo(
        filename="bulletin_de_paie_confidentiel.pdf",
        s3_key="uploads/sensitive-tenant/user-secret-id/bulletin_de_paie.pdf",
        size=1024,
        content_type="application/pdf",
        uploaded_at=datetime.now().isoformat(),
        presigned_url="https://s3.example.com/presigned",
    )


@pytest.mark.asyncio
async def test_cleanup_s3_success_logs_info_without_s3_key(
    mock_context: MainWorkflowContext,
    sample_file_info: FileInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_s3_key = sample_file_info.s3_key.get_secret_value()
    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_info=sample_file_info,
    )

    with patch(
        "document_ia_worker.workflow.step.download_file.download_file.S3Manager"
    ) as mock_s3_class:
        mock_s3_manager = MagicMock()
        mock_s3_manager.delete_file.return_value = True
        mock_s3_class.return_value = mock_s3_manager

        with caplog.at_level(logging.INFO):
            await step.cleanup(is_last_cleanup=True)

        mock_s3_manager.delete_file.assert_called_once_with(raw_s3_key)

    assert (
        f"S3 file deleted successfully for execution {step.execution_id}" in caplog.text
    )
    # Security requirement: raw s3_key must NEVER leak into logs
    assert raw_s3_key not in caplog.text


@pytest.mark.asyncio
async def test_cleanup_s3_failure_logs_warning_without_s3_key(
    mock_context: MainWorkflowContext,
    sample_file_info: FileInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_s3_key = sample_file_info.s3_key.get_secret_value()
    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_info=sample_file_info,
    )

    with patch(
        "document_ia_worker.workflow.step.download_file.download_file.S3Manager"
    ) as mock_s3_class:
        mock_s3_manager = MagicMock()
        mock_s3_manager.delete_file.return_value = False
        mock_s3_class.return_value = mock_s3_manager

        with caplog.at_level(logging.INFO):
            # Must not raise an exception even if S3 deletion returned False
            await step.cleanup(is_last_cleanup=True)

        mock_s3_manager.delete_file.assert_called_once_with(raw_s3_key)

    assert f"Failed to delete S3 file for execution {step.execution_id}" in caplog.text
    # Security requirement: raw s3_key must NEVER leak into logs
    assert raw_s3_key not in caplog.text


@pytest.mark.asyncio
async def test_cleanup_non_last_cleanup_does_not_delete_s3(
    mock_context: MainWorkflowContext,
    sample_file_info: FileInfo,
) -> None:
    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_info=sample_file_info,
    )

    with patch(
        "document_ia_worker.workflow.step.download_file.download_file.S3Manager"
    ) as mock_s3_class:
        mock_s3_manager = MagicMock()
        mock_s3_class.return_value = mock_s3_manager

        await step.cleanup(is_last_cleanup=False)

        mock_s3_manager.delete_file.assert_not_called()


@pytest.mark.asyncio
async def test_handle_s3_file_does_not_log_raw_s3_key(
    mock_context: MainWorkflowContext,
    sample_file_info: FileInfo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_s3_key = sample_file_info.s3_key.get_secret_value()
    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_info=sample_file_info,
    )

    with patch(
        "document_ia_worker.workflow.step.download_file.download_file.S3Manager"
    ) as mock_s3_class:
        mock_s3_manager = MagicMock()
        mock_s3_manager.download_file.return_value = None
        mock_s3_class.return_value = mock_s3_manager

        with caplog.at_level(logging.INFO):
            result, meta = await step._handle_s3_file(sample_file_info)

        assert result is not None
        mock_s3_manager.download_file.assert_called_once()

    assert f"Downloading file from S3 for execution: {step.execution_id}" in caplog.text
    # Security requirement: raw s3_key must NEVER leak into logs
    assert raw_s3_key not in caplog.text
