from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowType
from document_ia_worker.core.prompt.model.document_classification import DocumentClassification
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.save_workflow_result.save_workflow_result import (
    SaveWorkflowResultStep,
)
from document_ia_worker.workflow.step.step_result.llm_result import LLMClassificationResult


class TestSaveWorkflowResult:

    @pytest.mark.asyncio
    async def test_save_workflow_classification_result_persists_event_with_expected_payload(self, monkeypatch):
        # Arrange: context with deterministic start_time (timezone-aware to match code using UTC)
        start_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        ctx = MainWorkflowContext(execution_id="exec-123", start_time=start_time, number_of_step_executed=3)

        # Fake DB session
        fake_session = MagicMock()

        # Mock LLM result (Pydantic model inside LLMResult.data)
        classification = DocumentClassification(
            explanation="Detected as CNI with strong confidence",
            document_type="cni",
            confidence=0.97,
        )
        llm_classification_result = LLMClassificationResult(data=classification)

        # Instantiate step
        step = SaveWorkflowResultStep(
            main_workflow_context=ctx,
            workflow_id="wf-001",
            workflow_type=WorkflowType.CLASSIFICATION,
            database_session=fake_session,
        )

        # Remplace event_service par un stub avec la même signature que EventStoreService.emit_workflow_completed
        captured: dict[str, object] = {}

        async def fake_emit(*, workflow_id: str, execution_id: str, final_result: dict, total_processing_time_ms: int,
                            output_summary: dict, steps_completed: int):
            captured.update({
                "workflow_id": workflow_id,
                "execution_id": execution_id,
                "final_result": final_result,
                "total_processing_time_ms": total_processing_time_ms,
                "output_summary": output_summary,
                "steps_completed": steps_completed,
            })
            return SimpleNamespace(id="evt-42")

        step.event_service = SimpleNamespace(
            emit_workflow_completed=AsyncMock(side_effect=fake_emit)
        )

        # Inject workflow context
        step.inject_workflow_context({LLMClassificationResult.__name__: llm_classification_result})

        # Act
        await step.execute()

        # Assert: le stub a bien été appelé avec les bons paramètres
        assert captured, "event_service.emit_workflow_completed n'a pas été appelé"
        assert captured["workflow_id"] == "wf-001"
        assert captured["execution_id"] == "exec-123"
        assert captured["final_result"] == classification.model_dump()
        assert isinstance(captured["total_processing_time_ms"], int) and captured["total_processing_time_ms"] >= 0
        assert captured["output_summary"] == {}
        assert captured["steps_completed"] == 4  # number_of_step_executed + 1

    @pytest.mark.asyncio
    async def test_prepare_step_requires_llm_result(self):
        ctx = MainWorkflowContext(execution_id="exec-xyz", start_time=datetime.now(timezone.utc))
        step = SaveWorkflowResultStep(
            main_workflow_context=ctx,
            workflow_id="wf-abc",
            workflow_type=WorkflowType.CLASSIFICATION,
            database_session=MagicMock(),
        )

        with pytest.raises(ValueError):
            await step._prepare_step()
