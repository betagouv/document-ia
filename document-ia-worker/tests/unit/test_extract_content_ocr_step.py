from pathlib import Path

import cv2
import fitz
import numpy as np
import pytest
from pytesseract import get_tesseract_version

from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr import (
    ExtractContentOcrStep,
)
from document_ia_worker.workflow.step.preprocess_file.preprocess_file import PreprocessFileStep
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)


def _tesseract_available() -> bool:
    try:
        _ = get_tesseract_version()
        return True
    except Exception:
        return False


def _make_text_image(path: Path, text: str) -> Path:
    # Create a white image and draw high-contrast text, then save as PNG
    img = np.full((160, 600), 255, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, text, (20, 100), font, 2.0, (0,), 3, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), img)
    assert ok, f"Failed to write image at {path}"
    return path


class TestExtractContentOcrStep:

    @pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not available")
    @pytest.mark.asyncio
    async def test_ocr_from_pdf_fixture_two_pages_and_cleanup(self, main_workflow_context):
        """Run OCR starting from the PDF fixture via PreprocessFileStep, then ExtractContentOcrStep.
        Use the fixture as-is, assert we get OCR text for all pages, and verify cleanup removes temp files.
        """

        # Locate PDF fixture and ensure it exists
        fixtures_dir = Path(__file__).resolve().parents[1] / "fixtures"
        pdf_path = fixtures_dir / "test_download_file.pdf"
        assert pdf_path.exists(), "Fixture PDF 'test_download_file.pdf' is missing"

        # Count pages in the fixture
        try:
            with fitz.open(pdf_path) as doc:  # type: ignore[call-arg]
                page_count = doc.page_count
        except Exception as e:
            pytest.skip(f"Cannot open PDF fixture to count pages: {e}")
        assert page_count >= 1, "Fixture PDF must have at least 1 page"

        preprocess = PreprocessFileStep(main_workflow_context=main_workflow_context)
        # Inject a fake download result pointing to the fixture
        from document_ia_worker.workflow.step.step_result.download_file_result import (
            DownloadFileResult,
        )

        preprocess.inject_workflow_context(
            {DownloadFileResult.__name__: DownloadFileResult(file_path=str(pdf_path), content_type="application/pdf")}
        )

        # Execute preprocessing to generate page images
        preprocess_result, preprocess_meta = await preprocess.execute()
        assert len(preprocess_result.output_files_path) == page_count, (
            f"Expected {page_count} images from preprocessing, got {len(preprocess_result.output_files_path)}"
        )
        for img_path in preprocess_result.output_files_path:
            assert Path(img_path).exists(), f"Preprocessed image is missing: {img_path}"

        # Run OCR step on generated images
        ocr_step = ExtractContentOcrStep(main_workflow_context=main_workflow_context)
        ocr_step.tesseract_lang = "eng"
        ocr_step.inject_workflow_context({
            PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=preprocess_result.output_files_path)
        })
        ocr_result, ocr_meta = await ocr_step.execute()

        # Validate OCR output for all pages
        assert len(ocr_result.pages) == page_count, (
            f"Unexpected OCR page count: {len(ocr_result.pages)} (expected {page_count})"
        )
        for i, page in enumerate(ocr_result.pages, start=1):
            assert page.has_failed is False, f"OCR failed on page {i}"
            assert page.text is not None and page.text.strip() != "", f"Missing OCR text on page {i}"

        # Cleanup and ensure temp dir is removed
        tmp_dir = Path(preprocess.tmp_folder_path)
        assert tmp_dir.exists(), "Temporary directory should exist before cleanup"
        await preprocess.cleanup(False)
        assert not tmp_dir.exists(), f"Temporary directory should be deleted: {tmp_dir}"

    @pytest.mark.skipif(not _tesseract_available(), reason="Tesseract not available")
    @pytest.mark.asyncio
    async def test_ocr_timeout_is_handled(self, monkeypatch, tmp_path, main_workflow_context):
        """Simulate a Tesseract timeout and verify the exception path is handled gracefully.
        The first page raises a timeout-like exception; the second succeeds.
        """

        # Prepare two synthetic images
        img_timeout = _make_text_image(tmp_path / "timeout.png", "WILL TIMEOUT")
        img_ok = _make_text_image(tmp_path / "ok.png", "OK")

        # Build context and OCR step
        step = ExtractContentOcrStep(main_workflow_context=main_workflow_context)
        step.tesseract_lang = "eng"
        step.tesseract_timeout = 1  # very small, though we simulate timeout via monkeypatch

        # Inject PreprocessFileResult with both images
        step.inject_workflow_context(
            {PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=[str(img_timeout), str(img_ok)])}
        )

        # Monkeypatch image_to_string in the module under test to simulate a timeout on first call
        import document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr as ocr_mod
        call_count = {"n": 0}

        def fake_image_to_string(img, output_type, config, lang, timeout):  # noqa: ANN001
            call_count["n"] += 1
            if call_count["n"] == 1:
                import time

                time.sleep(0.05)
                raise RuntimeError("simulated tesseract timeout")
            return "Hello"

        monkeypatch.setattr(ocr_mod, "image_to_string", fake_image_to_string)

        # Execute OCR step
        result, meta = await step.execute()

        # Assertions: first page failed due to timeout, second succeeded
        assert len(result.pages) == 2
        assert result.pages[0].has_failed is True
        assert result.pages[0].text is None
        assert result.pages[1].has_failed is False
        assert result.pages[1].text is not None and result.pages[1].text.strip() != ""
