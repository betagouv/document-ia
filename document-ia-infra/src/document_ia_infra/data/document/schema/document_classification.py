from document_ia_schemas import SupportedDocumentType
from pydantic import BaseModel


class DocumentClassification(BaseModel):
    explanation: str
    document_type: SupportedDocumentType
    confidence: float
