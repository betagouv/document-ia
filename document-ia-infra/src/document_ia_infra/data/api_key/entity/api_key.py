from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from document_ia_infra.data.database import Base

if TYPE_CHECKING:
    from document_ia_infra.data.organization.entity.organization import (
        OrganizationEntity,
    )


class ApiKeyEntity(Base):
    __tablename__ = "api_key"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
        comment="Unique identifier of the api_key",
    )

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        comment="Id of the organization owning the api_key",
    )

    key_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Hash of the api_key"
    )

    prefix: Mapped[str] = mapped_column(
        String(12), nullable=False, comment="Prefix of the api_key"
    )

    status: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Active", comment="Status of the api_key"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        comment="api_key creation datetime",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="api_key update datetime",
    )

    organization: Mapped[Optional["OrganizationEntity"]] = relationship(
        "OrganizationEntity",
        back_populates="api_keys",
    )

    def __repr__(self) -> str:
        return (
            f"<ApiKeyEntity(id={self.id}, organization_id={self.organization_id}, "
            f"prefix={self.prefix}, status={self.status})>"
        )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "prefix": self.prefix,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
