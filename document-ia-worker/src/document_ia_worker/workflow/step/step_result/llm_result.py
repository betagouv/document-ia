from pydantic import BaseModel

from document_ia_worker.core.prompt.model.document_classification import (
    DocumentClassification,
)


class LLMStepMetadata(BaseModel):
    request_tokens: int
    response_tokens: int


class LLMResult(BaseModel):
    pass


class LLMClassificationResult(LLMResult):
    data: DocumentClassification


class LLMExtractionResult(LLMResult):
    data: BaseModel
