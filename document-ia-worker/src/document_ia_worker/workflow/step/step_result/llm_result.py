from pydantic import BaseModel

from document_ia_worker.core.prompt.model.document_classification import (
    DocumentClassification,
)


class LLMClassificationResult(BaseModel):
    data: DocumentClassification


class LLMResult(BaseModel):
    data: BaseModel
