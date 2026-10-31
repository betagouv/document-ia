import copy
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.barcode import Ants2DDoc, DataMatrix, QrCode
from document_ia_infra.data.event.schema.mappers.event_mapper import (
    convert_event_dto,
    convert_inner_event_dto,
)
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
from document_ia_schemas.cni import CNIModel


FIXTURES = json.loads(
    (Path(__file__).parents[3] / "fixtures/persisted_events.json").read_text()
)
EVENT_CLASSES = {
    EventType.WORKFLOW_EXECUTION_STARTED: WorkflowExecutionStartedEvent,
    EventType.WORKFLOW_EXECUTION_STEP_COMPLETED: WorkflowExecutionStepCompletedEvent,
    EventType.WORKFLOW_EXECUTION_COMPLETED: WorkflowExecutionCompletedEvent,
    EventType.WORKFLOW_EXECUTION_FAILED: WorkflowExecutionFailedEvent,
}


@pytest.mark.parametrize("name", FIXTURES["events"])
def test_persisted_events_decode_without_mutation(name):
    payload = copy.deepcopy(FIXTURES["common"] | FIXTURES["events"][name])
    original = copy.deepcopy(payload)
    event_type = EventType(payload["event_type"])
    event = convert_inner_event_dto(payload, event_type)
    assert type(event) is EVENT_CLASSES[event_type]
    assert event.version == payload["version"]
    assert event.execution_id == payload["execution_id"]
    assert payload == original

    dto = EventDTO(
        id=UUID(payload["event_id"]),
        workflow_id=payload["workflow_id"],
        organization_id=UUID(payload["organization_id"]),
        execution_id=payload["execution_id"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        event_type=event_type,
        event=payload,
    )
    record = convert_event_dto(dto)
    assert type(record.event) is type(event)
    # AUTRE uses the existing unparameterized BaseModel fallback, whose
    # equality is not defined by Pydantic. Its API projection is tested separately.
    excluded = {"final_result": {"extraction"}}
    assert record.event.model_dump(exclude=excluded) == event.model_dump(
        exclude=excluded
    )
    assert record.id == dto.id
    assert record.created_at == dto.created_at
    assert record.event_type == dto.event_type


def test_extraction_and_barcode_subclasses_survive_decoding():
    extraction_event = convert_inner_event_dto(
        FIXTURES["common"] | FIXTURES["events"]["completed_v1"],
        EventType.WORKFLOW_EXECUTION_COMPLETED,
    )
    assert isinstance(extraction_event, WorkflowExecutionCompletedEvent)
    extraction = extraction_event.final_result.extraction
    assert extraction is not None
    assert isinstance(extraction.properties, CNIModel)
    assert extraction.properties.nom == "EXEMPLE"
    assert extraction.properties.date_naissance.isoformat() == "1990-01-02"
    assert extraction_event.final_result.barcodes == []

    barcode_event = convert_inner_event_dto(
        FIXTURES["common"] | FIXTURES["events"]["completed_v2"],
        EventType.WORKFLOW_EXECUTION_COMPLETED,
    )
    assert isinstance(barcode_event, WorkflowExecutionCompletedEvent)
    qr, matrix, ants = barcode_event.final_result.barcodes
    assert isinstance(qr, QrCode) and qr.raw_data == "https://example.com/qr"
    assert isinstance(matrix, DataMatrix) and matrix.raw_data == "matrix-content"
    assert isinstance(ants, Ants2DDoc) and ants.typed_data[0].value == "Alice"
    assert ants.issue_date.isoformat() == "2026-01-01"


def test_all_event_types_are_covered():
    assert set(EVENT_CLASSES) == set(EventType)


def test_unknown_event_type_and_invalid_payload_still_fail():
    with pytest.raises(ValueError, match="Unsupported event type"):
        convert_inner_event_dto({}, "unknown")
    with pytest.raises(ValidationError):
        convert_inner_event_dto({}, EventType.WORKFLOW_EXECUTION_STARTED)
