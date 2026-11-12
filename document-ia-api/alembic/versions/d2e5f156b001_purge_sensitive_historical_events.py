"""Add index on anonymization_status in event_store

Revision ID: d2e5f156b001
Revises: 659b01a59fc4
Create Date: 2026-11-10 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d2e5f156b001"
down_revision: Union[str, Sequence[str], None] = "659b01a59fc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create index on anonymization_status to optimize purge queries."""
    op.create_index(
        "idx_event_store_anonymization_status",
        "event_store",
        ["anonymization_status", "created_at"],
    )


def downgrade() -> None:
    """Drop index on anonymization_status."""
    op.drop_index(
        "idx_event_store_anonymization_status",
        table_name="event_store",
    )
