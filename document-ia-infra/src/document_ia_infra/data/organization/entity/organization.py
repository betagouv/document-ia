from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from document_ia_infra.data.api_key.entity.api_key import ApiKeyEntity  # noqa: F401
from document_ia_infra.data.database import Base


class OrganizationEntity(Base):
    __tablename__ = "organization"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
        comment="Unique identifier for the organization",
    )

    contact_email: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Contact email for the organization"
    )

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Name of the organization"
    )

    platform_role: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Standard",
        comment="Platform role one of PlatformAdmin or Standard",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        comment="organization creation datetime",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="organization update datetime",
    )

    api_keys: Mapped[Optional[list["ApiKeyEntity"]]] = relationship(
        "ApiKeyEntity",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<OrganizationEntity(id={self.id}, name={self.name}, contact_email={self.contact_email}, "
            f"platform_role={self.platform_role})>"
        )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "contact_email": self.contact_email,
            "name": self.name,
            "platform_role": self.platform_role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
