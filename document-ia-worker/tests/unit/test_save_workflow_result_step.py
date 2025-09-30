from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.save_classification_workflow_result.save_workflow_result import (
    SaveWorkflowResultStep,
)
from document_ia_worker.workflow.step.step_result.llm_result import LLMResult
from document_ia_worker.core.prompt.model.DocumentClassification import (
    DocumentClassification,
)
from document_ia_infra.data.event.dto.event_type_enum import EventType

class TestSaveWorkflowResult:

    @pytest.mark.asyncio
    async def test_save_workflow_result_persists_event_with_expected_payload(self):
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
        llm_result = LLMResult(data=classification)

        # Instantiate step and inject a mocked repository
        step = SaveWorkflowResultStep(main_workflow_context=ctx, workflow_id="wf-001", database_session=fake_session)
        put_event_mock = AsyncMock(return_value=SimpleNamespace(id="evt-42"))
        step.event_repository = SimpleNamespace(put_event=put_event_mock)

        # Inject workflow context
        step.inject_workflow_context({LLMResult.__name__: llm_result})

        # Act
        await step.execute()

        # Assert: repository was called once with proper args
        assert put_event_mock.await_count == 1
        wf_id, exec_id, event_type, payload = put_event_mock.await_args.args

        assert wf_id == "wf-001"
        assert exec_id == "exec-123"
        assert event_type == EventType.WORKFLOW_EXECUTION_COMPLETED

        # Payload should be a dict produced by WorkflowExecutionCompletedEvent.model_dump(mode="json")
        assert isinstance(payload, dict)
        # Core fields present
        assert payload.get("workflow_id") == "wf-001"
        assert payload.get("execution_id") == "exec-123"
        assert "created_at" in payload
        assert "final_result" in payload and isinstance(payload["final_result"], dict)
        assert "total_processing_time_ms" in payload and isinstance(payload["total_processing_time_ms"], int)
        assert payload.get("steps_completed") == 4  # number_of_step_executed + 1
        assert payload.get("version") == 1

        # final_result matches the serialized LLM data
        assert payload["final_result"] == classification.model_dump()

        # processing time should be positive (not asserting exact value to avoid flakiness)
        assert payload["total_processing_time_ms"] >= 0


    @pytest.mark.asyncio
    async def test_prepare_step_requires_llm_result(self):
        ctx = MainWorkflowContext(execution_id="exec-xyz", start_time=datetime.now(timezone.utc))
        step = SaveWorkflowResultStep(main_workflow_context=ctx, workflow_id="wf-abc", database_session=MagicMock())

        with pytest.raises(ValueError):
            await step._prepare_step()
