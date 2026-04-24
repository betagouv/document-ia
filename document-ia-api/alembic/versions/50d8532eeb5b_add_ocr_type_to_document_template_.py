"""add ocr_type to document_template_embedding

Revision ID: 50d8532eeb5b
Revises: c3f4a5b6d7e8
Create Date: 2026-04-24 14:02:02.108605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50d8532eeb5b'
down_revision: Union[str, Sequence[str], None] = 'c3f4a5b6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'document_template_embedding',
        sa.Column('ocr_type', sa.String(length=100), nullable=True)
    )
    # Set default value for existing rows
    op.execute("UPDATE document_template_embedding SET ocr_type = 'TESSERACT' WHERE ocr_type IS NULL")
    # Make it non-nullable and add server default
    op.alter_column('document_template_embedding', 'ocr_type',
               existing_type=sa.String(length=100),
               nullable=False,
               server_default='TESSERACT')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('document_template_embedding', 'ocr_type')
