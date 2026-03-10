"""Add a field to event_store to store if the data has been anonymized

Revision ID: 659b01a59fc4
Revises: 4f4ecb83db27
Create Date: 2025-12-08 17:09:58.656420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '659b01a59fc4'
down_revision: Union[str, Sequence[str], None] = '4f4ecb83db27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "event_store",
        sa.Column(
            "anonymization_status",
            sa.String(length=255),
            nullable=False,
            server_default="PENDING",
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("event_store", "has_been_anonymized")
