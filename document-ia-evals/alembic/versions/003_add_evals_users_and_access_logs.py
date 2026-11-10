"""Add evals_users and evals_access_logs tables and seed admin user

Revision ID: 003
Revises: 002
Create Date: 2026-11-10 10:00:00.000000

"""

import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create evals_users and evals_access_logs tables and seed admin."""

    # 1. Create evals_users table
    evals_users_table = op.create_table(
        "evals_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.String(length=50),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_evals_users_email",
        "evals_users",
        ["email"],
        unique=True,
    )

    # 2. Create evals_access_logs table
    op.create_table(
        "evals_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evals_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_evals_access_logs_email",
        "evals_access_logs",
        ["email"],
    )
    op.create_index(
        "ix_evals_access_logs_created_at",
        "evals_access_logs",
        ["created_at"],
    )

    # 3. Seed initial admin user
    op.bulk_insert(
        evals_users_table,
        [
            {
                "id": uuid.uuid4(),
                "email": "nicolas.sagon@beta.gouv.fr",
                "role": "admin",
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    """Drop evals_access_logs and evals_users tables."""
    op.drop_index("ix_evals_access_logs_created_at", table_name="evals_access_logs")
    op.drop_index("ix_evals_access_logs_email", table_name="evals_access_logs")
    op.drop_table("evals_access_logs")

    op.drop_index("ix_evals_users_email", table_name="evals_users")
    op.drop_table("evals_users")
