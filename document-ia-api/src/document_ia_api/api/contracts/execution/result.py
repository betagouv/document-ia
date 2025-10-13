from typing import Any, Annotated

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    document_type: str
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]
    explanation: str


class ExtractionResult(BaseModel):
    classification: ClassificationResult
    extracted_fields: dict[str, Any]
