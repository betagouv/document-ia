from typing import Any

from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.event import EventStoreRecord, BaseEvent


def convert_event_dto(dto: EventDTO) -> EventStoreRecord:
    return EventStoreRecord(
        id=dto.id,
        workflow_id=dto.workflow_id,
        execution_id=dto.execution_id,
        created_at=dto.created_at,
        event_type=dto.event_type,
        event=convert_inner_event_dto(dto.event, dto.event_type),
    )


def convert_inner_event_dto(data: dict[str, Any], event_type: EventType) -> BaseEvent:
    match event_type:
        case EventType.WORKFLOW_EXECUTION_STARTED:
            from document_ia_infra.data.event.schema.event import (
                WorkflowExecutionStartedEvent,
            )

            return WorkflowExecutionStartedEvent(**data)
        case EventType.WORKFLOW_EXECUTION_STEP_COMPLETED:
            from document_ia_infra.data.event.schema.event import (
                WorkflowExecutionStepCompletedEvent,
            )

            return WorkflowExecutionStepCompletedEvent(**data)
        case EventType.WORKFLOW_EXECUTION_COMPLETED:
            from document_ia_infra.data.event.schema.event import (
                WorkflowExecutionCompletedEvent,
            )

            return WorkflowExecutionCompletedEvent(**data)
        case _:
            raise ValueError(f"Unsupported event type: {event_type}")
