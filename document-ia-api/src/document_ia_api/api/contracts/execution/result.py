from typing import Annotated

from pydantic import BaseModel, Field

from document_ia_infra.core.model.typed_generic_model import GenericProperty
from document_ia_schemas import SupportedDocumentType


class ClassificationResult(BaseModel):
    document_type: SupportedDocumentType
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]
    explanation: str


class ExtractionResult(BaseModel):
    type: SupportedDocumentType
    properties: list[GenericProperty] = Field(default=[])
