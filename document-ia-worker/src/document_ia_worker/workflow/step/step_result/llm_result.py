from pydantic import BaseModel

from document_ia_infra.data.event.schema.event import (
    DocumentClassification,
    DocumentExtraction,
)


class LLMStepMetadata(BaseModel):
    request_tokens: int
    response_tokens: int


class LLMResult(BaseModel):
    pass


class LLMClassificationResult(LLMResult):
    data: DocumentClassification


class LLMExtractionResult(LLMResult):
    data: DocumentExtraction[BaseModel]
