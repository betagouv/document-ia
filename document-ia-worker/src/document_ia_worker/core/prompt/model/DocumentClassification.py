from pydantic import BaseModel


class DocumentClassification(BaseModel):
    """Model for document classification results."""

    explanation: str
    document_type: str
    confidence: float
