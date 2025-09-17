from document_ia_api.schemas.events import EventStoreRecord
from document_ia_infra.data.event.dto.event_dto import EventDTO


def convert_event_dto(dto: EventDTO) -> EventStoreRecord:
    return EventStoreRecord(
        id=dto.id,
        workflow_id=dto.workflow_id,
        execution_id=dto.execution_id,
        created_at=dto.created_at,
        event_type=dto.event_type,
        event=dto.event,
        version=dto.version,
    )
