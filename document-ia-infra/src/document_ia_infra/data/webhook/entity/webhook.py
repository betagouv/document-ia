from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from document_ia_infra.data.database import Base


class WebHookEntity(Base):
    __tablename__ = "webhook"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
        comment="Unique identifier of the webhook",
    )

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        comment="Id of the organization owning the webhook",
    )

    url: Mapped[str] = mapped_column(
        String(2048), nullable=False, comment="URL of the webhook"
    )

    encrypted_headers: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, comment="Encrypted headers for the webhook"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        comment="webhook creation datetime",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="webhook update datetime",
    )

    def __repr__(self) -> str:
        return f"<WebHookEntity(id={self.id}, organization_id={self.organization_id}"

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "url": self.url,
            "encrypted_headers": self.encrypted_headers,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
