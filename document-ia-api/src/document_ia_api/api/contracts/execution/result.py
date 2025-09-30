from typing import Any

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    document_type: str
    confidence: float
    explanation: str


class ExtractionResult(BaseModel):
    classification_result: ClassificationResult
    extraction_result: dict[str, Any]
