from datetime import datetime, UTC
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from document_ia_api.application.services.execution_service import ExecutionService
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.document.schema.document_classification import DocumentClassification
from document_ia_infra.data.document.schema.document_extraction import DocumentExtraction
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_schemas import SupportedDocumentType

from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import \
    WorkflowExecutionCompletedEvent, CompletedEventResult
from document_ia_infra.data.event.schema.workflow.workflow_execution_failed_event import WorkflowExecutionFailedEvent
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import WorkflowExecutionStartedEvent


class SampleProps(BaseModel):
    first_name: str
    age: int | None = None


@pytest.fixture
def db_session() -> AsyncSession:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def service(db_session: AsyncSession) -> ExecutionService:
    return ExecutionService(db_session)


def _file_info() -> FileInfo:
    return FileInfo(
        filename="doc.pdf",
        size=1234,
        content_type="application/pdf",
        s3_key="k",
        uploaded_at=datetime.now(UTC).isoformat(),
        presigned_url="https://example.com",
    )


def test_get_event_model_started(service: ExecutionService):
    start_evt = WorkflowExecutionStartedEvent(
        event_id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        version=1,
        file_info=_file_info(),
        metadata={"k": "v"},
    )
    dto = EventDTO(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_STARTED,
        event=start_evt.model_dump(mode="json"),
    )
    res = service.get_event_model(dto, execution_id="exec", is_debug_mode=False)
    assert res.status == ExecutionStatus.STARTED
    assert res.data.file_name == "doc.pdf"


def test_get_event_model_failed(service: ExecutionService):
    failed_evt = WorkflowExecutionFailedEvent(
        event_id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        version=1,
        error_type="X",
        error_message="boom",
        failed_step="s",
        retry_count=1,
    )
    dto = EventDTO(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_FAILED,
        event=failed_evt.model_dump(mode="json"),
    )
    res = service.get_event_model(dto, execution_id="exec", is_debug_mode=False)
    assert res.status == ExecutionStatus.FAILED
    assert res.data.error_type == "X"


def test_get_event_model_completed_with_extraction_and_classification(service: ExecutionService, monkeypatch: pytest.MonkeyPatch):
    props = SampleProps(first_name="Alice", age=None)
    extraction = DocumentExtraction[SampleProps](
        title="t",
        type=SupportedDocumentType.CNI,
        properties=props,
    )
    classification = DocumentClassification(
        explanation="ok",
        document_type=SupportedDocumentType.CNI,
        confidence=0.9,
    )
    completed = WorkflowExecutionCompletedEvent(
        event_id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        version=1,
        final_result=CompletedEventResult(
            extraction=extraction,
            classification=classification,
            barcodes=[],
        ),
        total_processing_time_ms=100,
        output_summary={},
        steps_completed=3,
        workflow_metadata=[{"step": 1}],
    )

    # Stub resolve_extract_schema to return a lightweight object exposing document_model
    class DummySchema:
        document_model = SampleProps

    monkeypatch.setattr("document_ia_api.application.services.execution_service.resolve_extract_schema", lambda name: DummySchema())
    monkeypatch.setattr("document_ia_infra.data.document.schema.document_extraction.resolve_extract_schema", lambda name: DummySchema())

    dto = EventDTO(
        id=uuid4(),
        organization_id=uuid4(),
        workflow_id="wf",
        execution_id="exec",
        created_at=datetime.now(UTC),
        event_type=EventType.WORKFLOW_EXECUTION_COMPLETED,
        event=completed.model_dump(mode="json"),
    )

    res = service.get_event_model(dto, execution_id="exec", is_debug_mode=True)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.data.result.classification is not None
    assert res.data.result.extraction is not None
    # properties should include only present fields, with python names
    props_list = res.data.result.extraction.properties
    by_name: dict[str, Any] = {p.name: p.value for p in props_list}
    assert by_name["first_name"] == "Alice"
    assert "age" not in by_name  # None skipped
    assert res.data.result.workflow_metadata == [{"step": 1}]


def test__convert_extraction_result_unit(service: ExecutionService, monkeypatch: pytest.MonkeyPatch):
    props = SampleProps(first_name="Bob", age=42)
    extraction = DocumentExtraction[SampleProps](
        title="t",
        type=SupportedDocumentType.CNI,
        properties=props,
    )

    class DummySchema:
        document_model = SampleProps

    result = service._convert_extraction_result(extraction, DummySchema())
    assert result.type == SupportedDocumentType.CNI
    names = [p.name for p in result.properties]
    assert "first_name" in names and "age" in names
    # type inference
    types = {p.name: p.type for p in result.properties}
    assert types["first_name"] == "string"
    assert types["age"] == "number"
