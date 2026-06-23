import pytest
from pydantic import ValidationError

from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto


def _base_workflow(steps: list[dict]) -> dict:
    return {
        "id": "workflow-v2-test",
        "name": "Workflow V2 Test",
        "description": "Workflow de test",
        "version": "2.0.0",
        "enabled": True,
        "supported_file_types": ["application/pdf"],
        "max_file_size_mb": 25,
        "processing_timeout_minutes": 5,
        "steps": steps,
    }


def test_llm_extract_data_can_omit_document_type_after_classification():
    payload = _base_workflow(
        steps=[
            {"action": "download_file"},
            {"action": "llm_classify_document", "params": {}},
            {"action": "llm_extract_data", "params": {}},
            {"action": "save_workflow_result"},
        ]
    )

    dto = WorkflowV2Dto.model_validate(payload)
    assert dto.steps[2].action == "llm_extract_data"


def test_llm_extract_data_requires_document_type_without_classification():
    payload = _base_workflow(
        steps=[
            {"action": "download_file"},
            {"action": "llm_extract_data", "params": {}},
            {"action": "save_workflow_result"},
        ]
    )

    with pytest.raises(ValidationError) as exc_info:
        WorkflowV2Dto.model_validate(payload)

    assert "document_type is required" in str(exc_info.value)
