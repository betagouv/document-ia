"""Initial schema - experiments and observations tables

Revision ID: 001
Revises: 
Create Date: 2025-11-06 10:18:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create experiments and observations tables."""
    
    # Create experiments table
    op.create_table(
        'experiments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('label_studio_project_id', sa.Integer(), nullable=False),
        sa.Column('metric_name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('total_tasks', sa.Integer(), nullable=False),
        sa.Column('processed_count', sa.Integer(), nullable=False),
        sa.Column('average_score', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for experiments
    op.create_index('ix_experiments_project_metric', 'experiments', ['label_studio_project_id', 'metric_name', 'created_at'])
    op.create_index('ix_experiments_created_at', 'experiments', ['created_at'])
    
    # Create observations table
    op.create_table(
        'observations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('experiment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('prediction_id', sa.Integer(), nullable=False),
        sa.Column('model_version', sa.String(length=100), nullable=True),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('metric_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['experiment_id'], ['experiments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for observations
    op.create_index('ix_observations_experiment', 'observations', ['experiment_id'])
    op.create_index('ix_observations_task', 'observations', ['task_id'])
    op.create_index('ix_observations_model_version', 'observations', ['model_version'])


def downgrade() -> None:
    """Drop all tables."""
    
    # Drop observations table (must drop first due to foreign key)
    op.drop_index('ix_observations_model_version', table_name='observations')
    op.drop_index('ix_observations_task', table_name='observations')
    op.drop_index('ix_observations_experiment', table_name='observations')
    op.drop_table('observations')
    
    # Drop experiments table
    op.drop_index('ix_experiments_created_at', table_name='experiments')
    op.drop_index('ix_experiments_project_metric', table_name='experiments')
    op.drop_table('experiments')