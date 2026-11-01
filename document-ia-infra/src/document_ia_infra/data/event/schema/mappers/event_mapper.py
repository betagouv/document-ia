from typing import Any

from pydantic import ValidationError

from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import EventStoreRecord
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import (
    WorkflowExecutionCompletedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_failed_event import (
    WorkflowExecutionFailedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.event.schema.workflow.workflow_execution_step_completed_event import (
    WorkflowExecutionStepCompletedEvent,
)


type WorkflowEvent = (
    WorkflowExecutionStartedEvent
    | WorkflowExecutionStepCompletedEvent
    | WorkflowExecutionCompletedEvent
    | WorkflowExecutionFailedEvent
)


def decode_event_dto(dto: EventDTO) -> WorkflowEvent:
    """Validate the persisted envelope and payload together for every reader."""
    event = convert_inner_event_dto(dto.event, dto.event_type)
    for field in ("execution_id", "workflow_id", "organization_id"):
        if getattr(event, field) != getattr(dto, field):
            raise ValueError(f"Event envelope/payload mismatch: {field}")
    return event


def convert_event_dto(dto: EventDTO) -> EventStoreRecord:
    return EventStoreRecord(
        id=dto.id,
        workflow_id=dto.workflow_id,
        execution_id=dto.execution_id,
        organization_id=dto.organization_id,
        created_at=dto.created_at,
        event_type=dto.event_type,
        event=decode_event_dto(dto),
    )


def convert_inner_event_dto(
    data: dict[str, Any], event_type: EventType
) -> WorkflowEvent:
    """Decode persisted payloads for every reader; API projection stays separate."""
    if "event_type" in data and data["event_type"] != event_type:
        raise ValueError("Event envelope/payload mismatch: event_type")
    try:
        return _decode_payload(data, event_type)
    except ValidationError:
        # Pydantic errors include input values, including document contents.
        raise ValueError("Invalid persisted workflow event payload") from None


def _decode_payload(data: dict[str, Any], event_type: EventType) -> WorkflowEvent:
    match event_type:
        case EventType.WORKFLOW_EXECUTION_STARTED:
            return WorkflowExecutionStartedEvent(**data)
        case EventType.WORKFLOW_EXECUTION_STEP_COMPLETED:
            return WorkflowExecutionStepCompletedEvent(**data)
        case EventType.WORKFLOW_EXECUTION_COMPLETED:
            return WorkflowExecutionCompletedEvent(**data)
        case EventType.WORKFLOW_EXECUTION_FAILED:
            return WorkflowExecutionFailedEvent(**data)
        case _:
            raise ValueError("Unsupported event type")
