from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.workflow.dto.enums import LLMModel
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto
from document_ia_schemas import SupportedDocumentType
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step_factory_v2 import prepareStepListsV2


def _workflow(steps: list[dict]) -> WorkflowV2Dto:
    return WorkflowV2Dto.model_validate(
        {
            "id": "wf-test",
            "name": "Workflow test",
            "description": "Workflow test",
            "version": "2.0.0",
            "enabled": True,
            "supported_file_types": ["application/pdf"],
            "max_file_size_mb": 25,
            "processing_timeout_minutes": 5,
            "steps": steps,
        }
    )


def _event(workflow_configuration: WorkflowV2Dto) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="wf-test",
        execution_id="exec-1",
        organization_id=uuid4(),
        created_at=datetime.now(UTC),
        version=2,
        metadata={},
        file_url="https://example.com/document.pdf",
        classification_parameters=ClassificationParameters(
            llm_model=LLMModel.ALBERT_SMALL
        ),
        extraction_parameters=ExtractionParameters(
            llm_model=LLMModel.OPEN_WEIGHT_SMALL,
            document_type=SupportedDocumentType.CNI,
        ),
        workflow_configuration=workflow_configuration,
    )


def _context() -> MainWorkflowContext:
    return MainWorkflowContext(
        execution_id="exec-1",
        start_time=datetime.now(UTC),
        organization_id=uuid4(),
        steps_metadata=[],
    )


def test_prepare_step_lists_v2_instantiates_preprocess_file_step():
    workflow = _workflow(
        [
            {"action": "preprocess_file"},
        ]
    )
    context = _context()

    with patch(
        "document_ia_worker.workflow.step_factory_v2.PreprocessFileStep",
        return_value="preprocess_step",
    ) as mock_crop_step:
        result = prepareStepListsV2(
            event_v2=_event(workflow),
            workflow_context=context,
            session=MagicMock(spec=AsyncSession),
        )

    assert result == ["preprocess_step"]
    mock_crop_step.assert_called_once()
    assert mock_crop_step.call_args.args[0] == context


def test_prepare_step_lists_v2_passes_yoloworld_preprocess_params():
    workflow = _workflow(
        [
            {
                "action": "preprocess_file",
                "params": {
                    "yoloworld": {
                        "enabled": True,
                        "class_name": "document",
                        "margin": 8,
                        "confidence_threshold": 0.6,
                        "image_size": 640,
                    }
                },
            },
        ]
    )
    context = _context()

    with patch(
        "document_ia_worker.workflow.step_factory_v2.PreprocessFileStep",
        return_value="preprocess_step",
    ) as mock_preprocess_step:
        result = prepareStepListsV2(
            event_v2=_event(workflow),
            workflow_context=context,
            session=MagicMock(spec=AsyncSession),
        )

    assert result == ["preprocess_step"]
    assert mock_preprocess_step.call_args.args[0] == context
    params = mock_preprocess_step.call_args.kwargs["params"].yoloworld
    assert params.enabled is True
    assert params.class_name == "document"
    assert params.margin == 8
    assert params.confidence_threshold == 0.6
    assert params.image_size == 640
