from typing import Annotated, Literal

from pydantic import BaseModel, Field

from document_ia_schemas import SupportedDocumentType


class ClassificationResult(BaseModel):
    document_type: SupportedDocumentType
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]
    explanation: str


class ExtractionProperty(BaseModel):
    name: str = Field(description="Name of the extraction property")
    value: "str | float | int | bool | ExtractionProperty" = Field(
        description="Value of the extraction property"
    )
    type: Literal["str", "float", "int", "bool", "object"] = Field(
        description="Type of the extraction property"
    )


class ExtractionResult(BaseModel):
    type: SupportedDocumentType
    properties: list[ExtractionProperty]
