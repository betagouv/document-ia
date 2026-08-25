import logging
from typing import Any
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

logger = logging.getLogger(__name__)


def extract_pdf_text_if_available(
    file_path: str,
    *,
    enabled: bool,
    content_type: str | None,
) -> OcrResult | None:
    """Return native PDF text when the complete document is text-extractable."""
    if not enabled or content_type != "application/pdf":
        return None

    try:
        import pdf_inspector

        inspector: Any = pdf_inspector
        extraction = inspector.extract_pages_markdown(file_path)
        if extraction.pages_needing_ocr:
            logger.info(
                "pdf-inspector found pages requiring OCR for %s: %s",
                file_path,
                extraction.pages_needing_ocr,
            )
            return None

        pages: list[OcrResultPage] = []
        for page in extraction.pages:
            text = page.markdown.strip()
            if not text or page.needs_ocr:
                return None
            pages.append(
                OcrResultPage(
                    page_number=page.page + 1,
                    text=text,
                    has_failed=False,
                )
            )

        if not pages:
            return None
        logger.info(
            "Using native PDF text extracted by pdf-inspector for %s", file_path
        )
        return OcrResult(pages=pages)
    except Exception:
        logger.exception("pdf-inspector failed for %s; falling back to OCR", file_path)
        return None
