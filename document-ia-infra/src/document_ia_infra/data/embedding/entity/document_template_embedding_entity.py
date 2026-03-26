from typing import Any
from typing import Sequence
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import String, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.type_api import UserDefinedType

from document_ia_infra.data.database import Base


class VectorType(UserDefinedType[Any]):
    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def get_col_spec(self, **kwargs: Any):
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: Dialect):
        def process(value: Any) -> str | Any | None:
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                values = list(cast(Sequence[float | int], value))
                return "[" + ",".join(str(float(v)) for v in values) + "]"
            return value

        return process

    def result_processor(self, dialect: Dialect, coltype: Any):
        def process(value: Any) -> list[float] | Any | None:
            if value is None:
                return None
            if isinstance(value, str):
                stripped = value.strip("[]")
                if not stripped:
                    return []
                return [float(v) for v in stripped.split(",")]
            return value

        return process


class DocumentTemplateEmbeddingEntity(Base):
    __tablename__ = "document_template_embedding"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
        comment="Unique identifier of the template embedding",
    )
    document_type_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Document type code (e.g. CNI_FR)",
    )
    document_instance_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Source document instance identifier",
    )
    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Page number within the source document",
    )
    anonymized_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Anonymized OCR text used for reranking",
    )
    embedding: Mapped[list[float]] = mapped_column(
        VectorType(1024),
        nullable=False,
        comment="Embedding vector (1024 dimensions)",
    )

    def __repr__(self) -> str:
        return (
            "<DocumentTemplateEmbeddingEntity("
            f"id={self.id}, document_type_code={self.document_type_code}, "
            f"document_instance_id={self.document_instance_id}, page_number={self.page_number})>"
        )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "document_type_code": self.document_type_code,
            "document_instance_id": self.document_instance_id,
            "page_number": self.page_number,
            "anonymized_text": self.anonymized_text,
            "embedding": self.embedding,
        }
