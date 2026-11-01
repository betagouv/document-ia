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
    decode_event_dto,
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
    assert event.workflow_version == payload["version"]
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
    assert "workflow_version" not in record.model_dump(mode="json")["event"]
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
    with pytest.raises(ValueError, match="Invalid persisted workflow event payload"):
        convert_inner_event_dto({}, EventType.WORKFLOW_EXECUTION_STARTED)


def make_dto(name):
    payload = copy.deepcopy(FIXTURES["common"] | FIXTURES["events"][name])
    return EventDTO(
        id=UUID("33333333-3333-4333-8333-333333333333"),
        workflow_id=payload["workflow_id"],
        organization_id=UUID(payload["organization_id"]),
        execution_id=payload["execution_id"],
        created_at=datetime.fromisoformat("2026-01-02T12:00:00Z"),
        event_type=EventType(payload["event_type"]),
        event=payload,
    )


@pytest.mark.parametrize("name", FIXTURES["events"])
@pytest.mark.parametrize("other_type", EventType)
def test_subclasses_reject_other_types(name, other_type):
    dto = make_dto(name)
    if other_type == dto.event_type:
        return
    dto.event["event_type"] = other_type.value
    with pytest.raises(ValidationError) as error:
        EVENT_CLASSES[dto.event_type](**dto.event)
    assert any(e["loc"] == ("event_type",) for e in error.value.errors())
    with pytest.raises(ValueError, match="mismatch: event_type"):
        decode_event_dto(dto)


@pytest.mark.parametrize("name", FIXTURES["events"])
@pytest.mark.parametrize("field", ["execution_id", "workflow_id", "organization_id"])
@pytest.mark.parametrize("side", ["envelope", "payload"])
def test_envelope_identifiers_must_match(name, field, side):
    dto = make_dto(name)
    value = (
        UUID("44444444-4444-4444-8444-444444444444")
        if field == "organization_id"
        else "other-private-identifier"
    )
    if side == "envelope":
        setattr(dto, field, value)
    else:
        dto.event[field] = str(value)
    for decoder in (decode_event_dto, convert_event_dto):
        with pytest.raises(ValueError) as error:
            decoder(dto)
        assert str(error.value) == f"Event envelope/payload mismatch: {field}"


@pytest.mark.parametrize("name", FIXTURES["events"])
def test_legacy_omitted_type_and_store_owned_metadata_remain_valid(name):
    dto = make_dto(name)
    del dto.event["event_type"]
    event = decode_event_dto(dto)
    assert event.event_type == dto.event_type
    record = convert_event_dto(dto)
    # Store IDs and timestamps are generated independently of payload metadata.
    assert record.id != record.event.event_id
    assert record.created_at != record.event.created_at


@pytest.mark.parametrize("name", FIXTURES["events"])
def test_invalid_payload_errors_do_not_disclose_document_contents(name):
    dto = make_dto(name)
    dto.event["version"] = "PRIVATE-DOCUMENT-CONTENT"
    with pytest.raises(ValueError) as error:
        decode_event_dto(dto)
    assert str(error.value) == "Invalid persisted workflow event payload"
    assert error.value.__suppress_context__


def test_invalid_event_type_is_not_echoed():
    dto = make_dto("started_v1")
    dto.event["event_type"] = "PRIVATE-DOCUMENT-CONTENT"
    with pytest.raises(ValueError) as error:
        decode_event_dto(dto)
    assert str(error.value) == "Event envelope/payload mismatch: event_type"
