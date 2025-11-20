"""Add model_version_stats column to experiments table

Revision ID: 002
Revises: 001
Create Date: 2025-11-20 14:26:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add model_version_stats JSONB column to experiments table and processing_time_ms to observations table."""
    
    # Add model_version_stats column to experiments table to store mean processing times per model version
    op.add_column(
        'experiments',
        sa.Column('model_version_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    
    # Add processing_time_ms column to observations table to store individual processing times
    op.add_column(
        'observations',
        sa.Column('processing_time_ms', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Remove model_version_stats column from experiments table and processing_time_ms from observations table."""
    
    op.drop_column('observations', 'processing_time_ms')
    op.drop_column('experiments', 'model_version_stats')