from pathlib import Path

import fitz
import pytest

from document_ia_worker.core.ocr.pdf_inspector import extract_pdf_text_if_available
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr import (
    ExtractContentOcrStep,
)
from document_ia_worker.workflow.step.step_result.download_file_result import (
    DownloadFileResult,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)


def _make_pdf(path: Path, *, text: str | None) -> Path:
    document = fitz.open()
    page = document.new_page()
    if text is not None:
        page.insert_text((72, 72), text)
    document.save(str(path))
    document.close()
    return path


def test_extract_pdf_text_if_available_returns_page_text(tmp_path):
    pdf_path = _make_pdf(tmp_path / "text.pdf", text="Native PDF text")

    result = extract_pdf_text_if_available(
        str(pdf_path), enabled=True, content_type="application/pdf"
    )

    assert result is not None
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert "Native PDF text" in result.pages[0].text
    assert result.pages[0].has_failed is False


def test_extract_pdf_text_if_available_falls_back_for_scanned_pdf(tmp_path):
    pdf_path = _make_pdf(tmp_path / "scanned.pdf", text=None)

    result = extract_pdf_text_if_available(
        str(pdf_path), enabled=True, content_type="application/pdf"
    )

    assert result is None


@pytest.mark.asyncio
async def test_ocr_step_uses_native_text_without_reading_preprocessed_images(
    tmp_path, main_workflow_context
):
    pdf_path = _make_pdf(tmp_path / "text.pdf", text="Native PDF text")
    step = ExtractContentOcrStep(main_workflow_context, pdf_inspector_enabled=True)
    step.inject_workflow_context(
        {
            DownloadFileResult.__name__: DownloadFileResult(
                file_path=str(pdf_path), content_type="application/pdf"
            ),
            PreprocessFileResult.__name__: PreprocessFileResult(
                output_files_path=[str(tmp_path / "does-not-exist.png")]
            ),
        }
    )

    result, _ = await step.execute()

    assert len(result.pages) == 1
    assert "Native PDF text" in result.pages[0].text
