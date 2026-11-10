"""Purge sensitive historical events in event_store

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
    """Purge sensitive fields from historical events and set anonymization_status to DONE."""
    # WorkflowExecutionStarted : purge file_url, s3_file_info et metadata
    op.execute(
        """
        UPDATE event_store
        SET event = event - 'file_url' - 's3_file_info' || '{"s3_file_info": null, "file_url": null, "metadata": {}}'::jsonb,
            anonymization_status = 'DONE'
        WHERE event_type = 'WorkflowExecutionStarted' AND anonymization_status IN ('DONE', 'ERROR');
        """
    )

    # WorkflowExecutionStepCompleted : purge step_result et output_data
    op.execute(
        """
        UPDATE event_store
        SET event = event - 'output_data' || '{"step_result": {}, "output_data": null}'::jsonb,
            anonymization_status = 'DONE'
        WHERE event_type = 'WorkflowExecutionStepCompleted' AND anonymization_status IN ('DONE', 'ERROR');
        """
    )

    # WorkflowExecutionCompleted : purge output_summary et workflow_metadata
    op.execute(
        """
        UPDATE event_store
        SET event = event - 'workflow_metadata' || '{"final_result": {}, "output_summary": {}, "workflow_metadata": null}'::jsonb,
            anonymization_status = 'DONE'
        WHERE event_type = 'WorkflowExecutionCompleted' AND anonymization_status IN ('DONE', 'ERROR');
        """
    )

    # WorkflowExecutionFailed : purge error_message
    op.execute(
        """
        UPDATE event_store
        SET event = jsonb_set(event, '{error_message}', '"[PURGED]"'::jsonb),
            anonymization_status = 'DONE'
        WHERE event_type = 'WorkflowExecutionFailed' AND anonymization_status IN ('DONE', 'ERROR');
        """
    )


def downgrade() -> None:
    """Downgrade schema (data purge is irreversible)."""
    pass
