"""Enable pgvector extension

Revision ID: b1d2a3c4e5f6
Revises: 659b01a59fc4
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1d2a3c4e5f6"
down_revision: Union[str, Sequence[str], None] = "659b01a59fc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
