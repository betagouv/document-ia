from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import fitz

from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.preprocess_file.preprocess_file import (
    PreprocessFileStep,
)
from document_ia_worker.workflow.step.step_result.download_file_result import (
    DownloadFileResult,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE_PDF = FIXTURES_DIR / "test_download_file.pdf"


def _count_pdf_pages(pdf_path: Path) -> int:
    with fitz.open(pdf_path) as doc:  # type: ignore[call-arg]
        return doc.page_count

def _ensure_two_page_pdf(target_path: Path) -> Path:
    if target_path.exists():
        try:
            if _count_pdf_pages(target_path) == 2:
                return target_path
        except Exception:
            pass
    target_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()  # type: ignore[call-arg]
    try:
        for i in range(2):
            page = doc.new_page()
            page.insert_text((72, 72 + i * 20), f"Hello PDF page {i + 1}")
        doc.save(str(target_path))
    finally:
        doc.close()
    return target_path


class TestPreprocessFileStep:
    @pytest.mark.asyncio
    async def test_preprocess_pdf_creates_two_images_and_cleanup(self):
        # Ensure the fixture PDF has exactly 2 pages
        pdf_path = _ensure_two_page_pdf(SOURCE_PDF)
        assert pdf_path.exists(), "The fixture PDF is missing"
        assert _count_pdf_pages(pdf_path) == 2, "The fixture PDF must have 2 pages"

        # Build the context and the step
        ctx = MainWorkflowContext(execution_id=str(uuid4()), start_time=datetime.now(), steps_metadata=[])
        step = PreprocessFileStep(main_workflow_context=ctx)

        # Inject a simulated download result (unit test => no S3)
        dl_result = DownloadFileResult(
            file_path=str(pdf_path), content_type="application/pdf"
        )
        step.inject_workflow_context({DownloadFileResult.__name__: dl_result})

        # Execute the step
        result, metadata = await step.execute()
        assert metadata.step_name == "PreprocessFileStep"
        assert metadata.execution_time >= 0

        # Verify exactly 2 images are created
        assert len(result.output_files_path) == 2, (
            f"Unexpected number of images: {len(result.output_files_path)}"
        )
        # Files actually exist
        for img in result.output_files_path:
            p = Path(img)
            assert p.exists(), f"The generated image does not exist: {p}"
            assert p.suffix.lower() == ".png", "Outputs must be PNGs"

        # Temporary directory path
        tmp_dir = Path(step.tmp_folder_path)
        assert tmp_dir.exists() and tmp_dir.is_dir(), "The temporary folder must exist"

        # Cleanup and post-cleanup assertions
        await step.cleanup(False)
        assert not tmp_dir.exists(), f"The temporary folder should be deleted: {tmp_dir}"
        for img in result.output_files_path:
            assert not Path(img).exists(), f"The file should be deleted: {img}"
