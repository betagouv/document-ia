from dataclasses import dataclass
from uuid import UUID


@dataclass
class DocumentTemplateEmbeddingDTO:
    id: UUID
    document_type_code: str
    document_instance_id: str
    page_number: int
    anonymized_text: str
    embedding: list[float]
