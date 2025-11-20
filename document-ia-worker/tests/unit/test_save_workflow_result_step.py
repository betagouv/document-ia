from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4, UUID

import pytest
from pydantic import BaseModel

from document_ia_infra.data.document.schema.document_classification import DocumentClassification
from document_ia_infra.data.document.schema.document_extraction import DocumentExtraction
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import CompletedEventResult
from document_ia_schemas import SupportedDocumentType
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext, StepMetadata
from document_ia_worker.workflow.step.save_workflow_result.save_workflow_result import (
    SaveWorkflowResultStep,
)
from document_ia_worker.workflow.step.step_result.llm_result import LLMClassificationResult, LLMExtractionResult


class TestSaveWorkflowResult:

    @pytest.mark.asyncio
    async def test_save_workflow_classification_result_persists_event_with_expected_payload(self, monkeypatch):
        # Arrange: context with deterministic start_time (timezone-aware to match code using UTC)
        start_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        ctx = MainWorkflowContext(execution_id="exec-123", start_time=start_time, steps_metadata=[], number_of_step_executed=3,  organization_id=uuid4())

        # Fake DB session
        fake_session = MagicMock()

        # Mock LLM result (Pydantic model inside LLMResult.data)
        classification = DocumentClassification(
            explanation="Detected as CNI with strong confidence",
            document_type=SupportedDocumentType.CNI,
            confidence=0.97,
        )
        llm_classification_result = LLMClassificationResult(data=classification, request_tokens=5, response_tokens=7)

        # Instantiate step (note: workflow_type removed from constructor)
        step = SaveWorkflowResultStep(
            main_workflow_context=ctx,
            workflow_id="wf-001",
            database_session=fake_session,
        )

        # Replace event_service by a stub with the same signature as EventStoreService.emit_workflow_completed
        captured: dict[str, object] = {}

        async def fake_emit(*, workflow_id: str, execution_id: str, organization_id: UUID, final_result, total_processing_time_ms: int,
                            output_summary: dict, steps_completed: int, workflow_metadata):
            captured.update({
                "workflow_id": workflow_id,
                "organization_id": organization_id,
                "execution_id": execution_id,
                "final_result": final_result,
                "total_processing_time_ms": total_processing_time_ms,
                "output_summary": output_summary,
                "steps_completed": steps_completed,
                "workflow_metadata": workflow_metadata,
            })
            return SimpleNamespace(id="evt-42")

        step.event_service = SimpleNamespace(
            emit_workflow_completed=AsyncMock(side_effect=fake_emit)
        )

        # Inject workflow context
        step.inject_workflow_context({LLMClassificationResult.__name__: llm_classification_result})

        # Act
        await step.execute()

        # Assert: the stub was called with expected parameters
        assert captured, "event_service.emit_workflow_completed was not called"
        assert captured["workflow_id"] == "wf-001"
        assert captured["execution_id"] == "exec-123"
        final_result = cast(CompletedEventResult, captured["final_result"])
        assert isinstance(final_result, CompletedEventResult)
        assert final_result.classification == classification
        assert final_result.extraction is None
        assert final_result.barcodes == []
        assert isinstance(captured["total_processing_time_ms"], int) and captured["total_processing_time_ms"] >= 0
        assert captured["output_summary"] == {}
        assert captured["steps_completed"] == 4  # number_of_step_executed + 1
        assert captured["workflow_metadata"] == []

    @pytest.mark.asyncio
    async def test_save_workflow_extraction_result_persists_event_with_expected_payload(self):
        # Arrange
        start_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        ctx = MainWorkflowContext(execution_id="exec-extr", start_time=start_time, steps_metadata=[], number_of_step_executed=1,  organization_id=uuid4())
        fake_session = MagicMock()

        # LLMExtractionResult expects a pydantic BaseModel for data; create a minimal one

        class SimpleExtractionModel(BaseModel):
            field: str

        extraction_model = SimpleExtractionModel(field="value")
        extraction_payload = DocumentExtraction[SimpleExtractionModel](
            title="simple",
            type=SupportedDocumentType.CNI,
            properties=extraction_model,
        )
        llm_extraction_result = LLMExtractionResult(data=extraction_payload, request_tokens=3, response_tokens=4)

        step = SaveWorkflowResultStep(main_workflow_context=ctx, workflow_id="wf-extr", database_session=fake_session)

        captured = {}

        async def fake_emit(*, workflow_id: str, execution_id: str, organization_id: UUID, final_result, total_processing_time_ms: int,
                            output_summary: dict, steps_completed: int, workflow_metadata):
            captured.update({"final_result": final_result, "workflow_metadata": workflow_metadata})
            return SimpleNamespace(id="evt-99")

        step.event_service = SimpleNamespace(emit_workflow_completed=AsyncMock(side_effect=fake_emit))

        step.inject_workflow_context({LLMExtractionResult.__name__: llm_extraction_result})

        # Act
        await step.execute()

        # Assert
        final_result = cast(CompletedEventResult, captured["final_result"])
        assert isinstance(final_result, CompletedEventResult)
        assert final_result.extraction == extraction_payload
        assert final_result.classification is None
        assert captured["workflow_metadata"] == []

    @pytest.mark.asyncio
    async def test_save_workflow_includes_workflow_metadata(self):
        # Arrange: create context with non-empty steps_metadata
        start_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        steps_md = [StepMetadata(step_name="ocr", execution_time=120.5)]
        ctx = MainWorkflowContext(execution_id="exec-meta", start_time=start_time, steps_metadata=steps_md, number_of_step_executed=2, organization_id=uuid4())
        fake_session = MagicMock()

        classification = DocumentClassification(
            explanation="ok",
            document_type=SupportedDocumentType.CNI,
            confidence=0.5,
        )
        llm_classification_result = LLMClassificationResult(data=classification, request_tokens=2, response_tokens=2)

        step = SaveWorkflowResultStep(main_workflow_context=ctx, workflow_id="wf-meta", database_session=fake_session)

        captured = {}

        async def fake_emit(*, workflow_id: str, execution_id: str, organization_id: UUID, final_result, total_processing_time_ms: int,
                            output_summary: dict, steps_completed: int, workflow_metadata):
            captured.update({"workflow_metadata": workflow_metadata})
            return SimpleNamespace(id="evt-meta")

        step.event_service = SimpleNamespace(emit_workflow_completed=AsyncMock(side_effect=fake_emit))

        step.inject_workflow_context({LLMClassificationResult.__name__: llm_classification_result})

        # Act
        await step.execute()

        # Assert the workflow_metadata passed through unchanged
        assert captured["workflow_metadata"] == steps_md
