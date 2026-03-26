from pydantic import BaseModel

from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
)
from document_ia_infra.data.document.schema.document_extraction import (
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


class LLMEmbeddingResult(LLMResult):
    embeddings_by_page: list[list[float]]
