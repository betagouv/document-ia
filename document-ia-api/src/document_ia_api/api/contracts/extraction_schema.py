from typing import Any

from pydantic import BaseModel, Field


class APIExtractionSchemaResult(BaseModel):
    document_type: str = Field(
        description="Document type of the extraction",
        examples=["cni", "avis_imposition"],
    )
    model: dict[str, Any] = Field(description="JSON schema for the extraction")
