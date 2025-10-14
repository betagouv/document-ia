from typing import Any, Annotated

from pydantic import BaseModel, Field, ConfigDict

from document_ia_infra.core.model.types.secret import SecretPayloadDict


class ClassificationResult(BaseModel):
    document_type: str
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]
    explanation: str


class ExtractionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    classification: ClassificationResult
    extracted_fields: SecretPayloadDict[Any]
