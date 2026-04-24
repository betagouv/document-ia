from typing import Sequence
from typing import cast as typing_cast

from sqlalchemy import select, String
from sqlalchemy import bindparam, Integer
from sqlalchemy import cast
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.core.ocr_type import OCRType
from document_ia_infra.data.embedding.dto.document_template_embedding_dto import (
    DocumentTemplateEmbeddingDTO,
)
from document_ia_infra.data.embedding.entity.document_template_embedding_entity import (
    DocumentTemplateEmbeddingEntity,
)
from document_ia_infra.data.embedding.mapper.document_template_embedding_mapper import (
    dto_to_entity,
    entity_to_dto,
)


class DocumentTemplateEmbeddingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, dto: DocumentTemplateEmbeddingDTO
    ) -> DocumentTemplateEmbeddingDTO:
        entity = dto_to_entity(dto)
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity_to_dto(entity)

    async def create_many(
        self, dtos: Sequence[DocumentTemplateEmbeddingDTO]
    ) -> list[DocumentTemplateEmbeddingDTO]:
        entities = [dto_to_entity(dto) for dto in dtos]
        self.session.add_all(entities)
        await self.session.flush()
        for entity in entities:
            await self.session.refresh(entity)
        return [entity_to_dto(entity) for entity in entities]

    async def list_by_document_type_code(
        self,
        document_type_code: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[DocumentTemplateEmbeddingDTO]:
        query = select(DocumentTemplateEmbeddingEntity).where(
            DocumentTemplateEmbeddingEntity.document_type_code == document_type_code
        )
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        result = await self.session.execute(query)
        entities = result.scalars().all()
        return [entity_to_dto(entity) for entity in entities]

    async def list_by_document_instance_id(
        self,
        document_instance_id: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[DocumentTemplateEmbeddingDTO]:
        query = select(DocumentTemplateEmbeddingEntity).where(
            DocumentTemplateEmbeddingEntity.document_instance_id == document_instance_id
        )
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)

        result = await self.session.execute(query)
        entities = result.scalars().all()
        return [entity_to_dto(entity) for entity in entities]

    def _vector_to_sql(self, vector: Sequence[float]) -> str:
        values = list(vector)
        return "[" + ",".join(str(float(v)) for v in values) + "]"

    def _parse_vector_value(self, value: object) -> list[float]:
        if isinstance(value, list):
            values = list(typing_cast(Sequence[float | int], value))
            return [float(v) for v in values]
        if isinstance(value, str):
            stripped = value.strip("[]")
            if not stripped:
                return []
            parts = stripped.split(",")
            return [float(v) for v in parts]
        return []

    async def find_top_similar(
        self,
        *,
        query_vector: Sequence[float],
        limit: int = 5,
        ocr_type: str | None = None,
        page_number: int | None = None,
        allowed_document_types: Sequence[str] | None = None,
    ) -> list[tuple[DocumentTemplateEmbeddingDTO, float]]:
        query_vec = self._vector_to_sql(query_vector)

        similarity_expr = 1 - (
            DocumentTemplateEmbeddingEntity.embedding.op("<=>")(
                cast(
                    bindparam("query_vec"),
                    DocumentTemplateEmbeddingEntity.embedding.type,
                )
            )
        )

        stmt = select(
            DocumentTemplateEmbeddingEntity.id,
            DocumentTemplateEmbeddingEntity.document_type_code,
            DocumentTemplateEmbeddingEntity.document_instance_id,
            DocumentTemplateEmbeddingEntity.ocr_type,
            DocumentTemplateEmbeddingEntity.page_number,
            DocumentTemplateEmbeddingEntity.anonymized_text,
            DocumentTemplateEmbeddingEntity.embedding,
            similarity_expr.label("similarity"),
        )

        if ocr_type is not None:
            stmt = stmt.where(
                DocumentTemplateEmbeddingEntity.ocr_type
                == cast(bindparam("ocr_type", type_=String(100)), String(100))
            )

        if page_number is not None:
            stmt = stmt.where(
                DocumentTemplateEmbeddingEntity.page_number
                == cast(bindparam("page_number", type_=Integer), Integer)
            )

        if allowed_document_types:
            stmt = stmt.where(
                DocumentTemplateEmbeddingEntity.document_type_code.in_(
                    bindparam("allowed_document_types", expanding=True)
                )
            )

        stmt = stmt.order_by(
            DocumentTemplateEmbeddingEntity.embedding.op("<=>")(
                cast(
                    bindparam("query_vec"),
                    DocumentTemplateEmbeddingEntity.embedding.type,
                )
            )
        ).limit(bindparam("limit", type_=Integer))

        params = {
            "query_vec": query_vec,
            "limit": limit,
            "ocr_type": ocr_type,
            "page_number": page_number,
            "allowed_document_types": list(allowed_document_types or []),
        }

        result = await self.session.execute(stmt, params)
        rows = result.mappings().all()

        output: list[tuple[DocumentTemplateEmbeddingDTO, float]] = []
        for row in rows:
            dto = DocumentTemplateEmbeddingDTO(
                id=row["id"],
                document_type_code=row["document_type_code"],
                document_instance_id=row["document_instance_id"],
                ocr_type=OCRType(row["ocr_type"]),
                page_number=row["page_number"],
                anonymized_text=row["anonymized_text"],
                embedding=self._parse_vector_value(row["embedding"]),
            )
            similarity = float(row["similarity"])
            output.append((dto, similarity))

        return output
