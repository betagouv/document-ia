"""create organization api_key and webhook tables

Revision ID: 19d1c6ddd15d
Revises: 9f3c1a2b7d84
Create Date: 2025-11-05 13:56:59.287304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19d1c6ddd15d'
down_revision: Union[str, Sequence[str], None] = '9f3c1a2b7d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column(
            "id", sa.UUID(), nullable=False, comment="Unique identifier for the organization"
        ),
        sa.Column(
            "contact_email",
            sa.String(length=255),
            nullable=False,
            comment="Contact email for the organization",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="Name of the organization",
        ),
        sa.Column(
            "platform_role",
            sa.String(length=255),
            nullable=False,
            default="Standard",
            comment="Platform role one of PlatformAdmin or Standard",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False,
            comment="organization creation datetime",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text('CURRENT_TIMESTAMP'),
            nullable=False,
            comment="organization update datetime",
        ),
        sa.PrimaryKeyConstraint("id")
    )

    op.create_table(
        "api_key",
        sa.Column(
            "id", sa.UUID(), nullable=False, comment="Unique identifier of the api_key"
        ),
        sa.Column(
            "organization_id",
            sa.UUID(),
            nullable=False,
            comment="Id of the organization owning the api_key",
        ),
        sa.Column(
            "key_hash",
            sa.String(length=255),
            nullable=False,
            comment="Hash of the api_key",
        ),
        sa.Column(
            "prefix",
            sa.String(length=12),
            nullable=False,
            comment="Prefix of the api_key",
        ),
        sa.Column(
            "status",
            sa.String(length=255),
            nullable=False,
            default="Active",
            comment="Status of the api_key",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment="api_key creation datetime",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment="api_key update datetime",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_api_key_organization_id",
            ondelete="CASCADE",
        )
    )

    op.create_table(
        "webhook",
        sa.Column(
            "id", sa.UUID(), nullable=False, comment="Unique identifier of the webhook"
        ),
        sa.Column(
            "organization_id",
            sa.UUID(),
            nullable=False,
            comment="Id of the organization owning the webhook",
        ),
        sa.Column(
            "url",
            sa.String(length=2048),
            nullable=False,
            comment="URL of the webhook",
        ),
        sa.Column(
            "encrypted_headers",
            sa.Text(),
            nullable=True,
            comment="Encrypted headers for the webhook",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment="webhook creation datetime",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment="webhook update datetime",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_webhook_organization_id",
            ondelete="CASCADE",
        )
    )

    op.add_column(
        "event_store",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organization.id", ondelete="SET NULL"),
            nullable=True,
            comment="Identifier of the organization associated with the event",
        )
    )


def downgrade() -> None:
    op.drop_column("event_store", "organization_id")

    op.drop_table("webhook")
    op.drop_table("api_key")
    op.drop_table("organization")
