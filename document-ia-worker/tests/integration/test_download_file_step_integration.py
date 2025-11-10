from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.s3.s3_manager import S3Manager
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE_PDF = FIXTURES_DIR / "test_download_file.pdf"


def _ensure_s3_available() -> bool:
    """Returns True if S3 manager can access the configured bucket."""
    try:
        m = S3Manager()
        return m.check_bucket_exists()
    except Exception:
        return False


class TestDownloadFileStepIntegration:
    @pytest.mark.skipif(not _ensure_s3_available(), reason="S3 not available")
    @pytest.mark.asyncio
    async def test_download_file_step_success(self, tmp_path, main_workflow_context):

        assert (
            SOURCE_PDF.exists()
        ), "Fixture file test_download_file.pdf is missing"

        # Prepare content and metadata
        key = f"integration/tests/{uuid4()}/test_download_file.pdf"
        content = SOURCE_PDF.read_bytes()
        source_size = len(content)
        content_type = "application/pdf"

        s3 = S3Manager()

        # Actual upload to S3
        s3.upload_file(file_key=key, file_data=content, content_type=content_type)

        try:
            # Build FileInfo for the step
            file_info = FileInfo(
                filename=SOURCE_PDF.name,
                s3_key=key,
                size=source_size,
                content_type=content_type,
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                presigned_url="",
            )

            step = DownloadFileStep(main_workflow_context=main_workflow_context, file_info=file_info)

            # Execute the step (actual download from S3)
            result, metadata = await step.execute()

            # Assertions before cleanup
            downloaded_path = Path(result.file_path)
            tmp_dir = Path(step.tmp_folder_path)
            assert downloaded_path.exists(), "Downloaded file does not exist"
            assert tmp_dir.exists() and tmp_dir.is_dir(), "Temporary folder does not exist"
            downloaded_size = downloaded_path.stat().st_size
            assert (
                    downloaded_size == source_size
            ), f"Different size: expected {source_size}, got {downloaded_size}"

            # Validate returned metadata (StepMetadata)
            assert metadata.step_name == "DownloadFileStep"
            assert metadata.execution_time >= 0

            # Local cleanup (not last): tmp directory should be removed, S3 object should still exist
            await step.cleanup(False)
            assert (
                not tmp_dir.exists()
            ), f"Temporary folder should be deleted: {tmp_dir}"

            # S3 object still present after non-last cleanup
            info = s3.get_file_info(key)
            assert info is not None, "S3 object should still exist after non-last cleanup"

            # Final cleanup: request deletion from S3
            await step.cleanup(True)

            # After last cleanup the S3 object should be deleted
            info_after = s3.get_file_info(key)
            assert info_after is None, "S3 object should be deleted on last cleanup"

        finally:
            # Ensure S3 object removed (idempotent)
            s3.delete_file(key)

    @pytest.mark.skipif(not _ensure_s3_available(), reason="S3 not available")
    @pytest.mark.asyncio
    async def test_download_file_step_missing_key_raises_retryable(self, tmp_path, main_workflow_context):

        # Nonexistent key
        key = f"integration/tests/{uuid4()}/missing.pdf"

        file_info = FileInfo(
            filename="missing.pdf",
            s3_key=key,
            size=0,
            content_type="application/pdf",
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            presigned_url="",
        )

        step = DownloadFileStep(main_workflow_context=main_workflow_context, file_info=file_info)

        # Preparation creates the temporary folder even if the download fails
        with pytest.raises(RetryableException):
            await step.execute()

        tmp_dir = Path(step.tmp_folder_path)
        assert tmp_dir.exists(), "Temporary folder should exist after _prepare_step"

        # Local cleanup and assertion
        await step.cleanup(False)
        assert (
            not tmp_dir.exists()
        ), f"Temporary folder should be deleted: {tmp_dir}"

        # Last cleanup should attempt to delete from S3 but not raise even if object missing
        await step.cleanup(True)
