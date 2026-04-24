from typing import Optional
from pydantic import BaseModel
from document_ia_infra.core.ocr_type import OCRType


class OcrResultPage(BaseModel):
    page_number: int
    text: Optional[str]
    has_failed: bool


class OcrResult(BaseModel):
    pages: list[OcrResultPage]
    ocr_type: Optional[OCRType] = None
