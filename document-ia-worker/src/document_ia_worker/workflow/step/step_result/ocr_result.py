from typing import Optional
from pydantic import BaseModel


class OcrResultPage(BaseModel):
    page_number: int
    text: Optional[str]
    has_failed: bool


class OcrResult(BaseModel):
    pages: list[OcrResultPage]
