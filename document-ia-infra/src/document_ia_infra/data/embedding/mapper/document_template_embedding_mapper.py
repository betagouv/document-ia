from document_ia_infra.core.ocr_type import OCRType
from document_ia_infra.data.embedding.dto.document_template_embedding_dto import (
    DocumentTemplateEmbeddingDTO,
)
from document_ia_infra.data.embedding.entity.document_template_embedding_entity import (
    DocumentTemplateEmbeddingEntity,
)


def entity_to_dto(
    entity: DocumentTemplateEmbeddingEntity,
) -> DocumentTemplateEmbeddingDTO:
    return DocumentTemplateEmbeddingDTO(
        id=entity.id,
        document_type_code=entity.document_type_code,
        document_instance_id=entity.document_instance_id,
        ocr_type=OCRType(entity.ocr_type),
        page_number=entity.page_number,
        anonymized_text=entity.anonymized_text,
        embedding=list(entity.embedding),
    )


def dto_to_entity(
    dto: DocumentTemplateEmbeddingDTO,
) -> DocumentTemplateEmbeddingEntity:
    return DocumentTemplateEmbeddingEntity(
        id=dto.id,
        document_type_code=dto.document_type_code,
        document_instance_id=dto.document_instance_id,
        ocr_type=dto.ocr_type.value,
        page_number=dto.page_number,
        anonymized_text=dto.anonymized_text,
        embedding=dto.embedding,
    )
