from typing import Dict, Any, Optional

from pydantic import Field

from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import BaseEvent


class WorkflowExecutionStepCompletedEvent(BaseEvent):
    """Event triggered for each workflow step completion."""

    event_type: EventType = Field(
        default=EventType.WORKFLOW_EXECUTION_STEP_COMPLETED, description="Event type"
    )
    step_name: str = Field(description="Name of the completed step")
    step_result: Dict[str, Any] = Field(description="Result data from the step")
    execution_time_ms: int = Field(description="Step execution time in milliseconds")
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Step output data"
    )
