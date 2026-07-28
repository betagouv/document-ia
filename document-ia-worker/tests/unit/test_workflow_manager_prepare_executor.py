from datetime import datetime, UTC
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.workflow.dto.enums import LLMModel
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowDTO
from document_ia_infra.redis.model.workflow_execution_message import WorkflowExecutionMessage
from document_ia_schemas import SupportedDocumentType
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.workflow_manager import WorkflowManager


def _build_workflow(steps: list[str]) -> WorkflowDTO:
    return WorkflowDTO(
        id="wf-test",
        name="Workflow test",
        description="Workflow test",
        version="1.0.0",
        enabled=True,
        supported_file_types=["application/pdf"],
        steps=steps,
        llm_model=LLMModel.OPEN_WEIGHT_MEDIUM,
        max_file_size_mb=25,
        processing_timeout_minutes=5,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _build_event(version: int) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="wf-test",
        execution_id="exec-1",
        organization_id=uuid4(),
        created_at=datetime.now(UTC),
        version=version,
        metadata={},
        file_url="https://example.com/document.pdf",
        classification_parameters=ClassificationParameters(
            llm_model=LLMModel.ALBERT_SMALL
        ),
        extraction_parameters=ExtractionParameters(
            llm_model=LLMModel.OPEN_WEIGHT_SMALL,
            document_type=SupportedDocumentType.CNI,
        ),
    )


def _build_context() -> MainWorkflowContext:
    return MainWorkflowContext(
        execution_id="exec-1",
        start_time=datetime.now(UTC),
        organization_id=uuid4(),
        classification_parameters=ClassificationParameters(
            llm_model=LLMModel.ALBERT_SMALL
        ),
        extraction_parameters=ExtractionParameters(
            llm_model=LLMModel.OPEN_WEIGHT_SMALL,
            document_type=SupportedDocumentType.CNI,
        ),
        steps_metadata=[],
    )


def _build_manager() -> WorkflowManager:
    with patch("document_ia_worker.workflow.workflow_manager.setup_logging_worker"), patch(
        "document_ia_worker.workflow.workflow_manager.execution_id_var"
    ) as mock_exec_var, patch(
        "document_ia_worker.workflow.workflow_manager.agg_buffer_var"
    ) as mock_agg_var, patch(
        "document_ia_worker.workflow.workflow_manager.start_time_var"
    ) as mock_start_var, patch(
        "document_ia_worker.workflow.workflow_manager.Publisher"
    ), patch("document_ia_worker.workflow.workflow_manager.RedisManager"):
        mock_exec_var.set.return_value = object()
        mock_agg_var.set.return_value = object()
        mock_start_var.set.return_value = object()
        return WorkflowManager(
            WorkflowExecutionMessage(workflow_execution_id="exec-1"),
            retry_count=0,
        )


def test_prepare_executor_uses_v1_factory_for_event_v1():
    manager = _build_manager()
    manager.workflow = _build_workflow(["download_file"])
    manager.event_dto = MagicMock()
    manager.event_data = _build_event(version=1)
    manager.main_workflow_context = _build_context()

    with patch(
        "document_ia_worker.workflow.workflow_manager.prepareStepListsV1",
        return_value=["from_factory"],
    ) as mock_factory:
        manager._prepare_executor(MagicMock(spec=AsyncSession))

    assert manager.step_list == ["from_factory"]
    mock_factory.assert_called_once()


def test_prepare_executor_uses_v2_factory_for_event_v2():
    manager = _build_manager()
    manager.workflow = _build_workflow(["download_file"])
    manager.event_dto = MagicMock()
    manager.event_data = _build_event(version=2)
    manager.main_workflow_context = _build_context()
    session = MagicMock(spec=AsyncSession)

    with patch(
        "document_ia_worker.workflow.workflow_manager.prepareStepListsV1"
    ) as mock_factory, patch(
        "document_ia_worker.workflow.workflow_manager.prepareStepListsV2",
        return_value=["from_v2_factory"],
    ) as mock_v2_factory:
        manager._prepare_executor(session)

    mock_factory.assert_not_called()
    mock_v2_factory.assert_called_once_with(
        event_v2=manager.event_data,
        workflow_context=manager.main_workflow_context,
        session=session,
    )
    assert manager.step_list == ["from_v2_factory"]
