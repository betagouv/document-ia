from dataclasses import dataclass
from uuid import UUID
from document_ia_infra.core.ocr_type import OCRType


@dataclass
class DocumentTemplateEmbeddingDTO:
    id: UUID
    document_type_code: str
    document_instance_id: str
    ocr_type: OCRType
    page_number: int
    anonymized_text: str
    embedding: list[float]
