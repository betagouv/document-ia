from dataclasses import dataclass
from typing import Optional


@dataclass
class OcrResultPage:
    page_number: int
    text: Optional[str]
    has_failed: bool


@dataclass
class OcrResult:
    pages: list[OcrResultPage]
