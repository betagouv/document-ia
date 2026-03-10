"""Drop version column from event_store

Revision ID: 9f3c1a2b7d84
Revises: 5876b08c4f42
Create Date: 2025-09-24 10:15:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f3c1a2b7d84"
down_revision: Union[str, Sequence[str], None] = "5876b08c4f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove the 'version' column from event_store, along with dependent objects."""
    # Drop index that references the column if it exists
    try:
        op.drop_index("idx_event_store_execution_version", table_name="event_store")
    except Exception:
        # Index may not exist; proceed with CASCADE drop
        pass

    # Use CASCADE to drop any dependent constraints (e.g., unique constraint on (..., version))
    op.execute("ALTER TABLE event_store DROP COLUMN version CASCADE")


def downgrade() -> None:
    """Re-add the 'version' column (initialized to 1), and restore related index/constraint."""
    # Add the column back with a server default of 1 to initialize existing rows
    op.add_column(
        "event_store",
        sa.Column("version", sa.Integer(), nullable=True, server_default=sa.text("1")),
    )

    # Make it NOT NULL after backfill
    op.alter_column("event_store", "version", nullable=False, server_default=None)

    # Recreate the index used previously
    op.create_index(
        "idx_event_store_execution_version",
        "event_store",
        ["execution_id", "version"],
        unique=False,
    )
