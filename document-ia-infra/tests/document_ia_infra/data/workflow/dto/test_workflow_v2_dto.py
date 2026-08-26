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


def test_preprocess_file_accepts_yoloworld_with_defaults():
    payload = _base_workflow(
        steps=[
            {"action": "download_file"},
            {"action": "preprocess_file"},
            {"action": "save_workflow_result"},
        ]
    )

    dto = WorkflowV2Dto.model_validate(payload)

    assert dto.steps[1].action == "preprocess_file"
    assert dto.steps[1].params.yoloworld.enabled is False
    assert dto.steps[1].params.yoloworld.class_name == "book"
    assert dto.steps[1].params.yoloworld.margin == 20
    assert dto.steps[1].params.yoloworld.confidence_threshold == 0.25


def test_preprocess_file_accepts_custom_yoloworld_params():
    payload = _base_workflow(
        steps=[
            {"action": "download_file"},
            {
                "action": "preprocess_file",
                "params": {
                    "yoloworld": {
                        "enabled": True,
                        "class_name": "document",
                        "margin": 5,
                        "confidence_threshold": 0.7,
                        "image_size": 640,
                    }
                },
            },
            {"action": "save_workflow_result"},
        ]
    )

    dto = WorkflowV2Dto.model_validate(payload)

    params = dto.steps[1].params.yoloworld
    assert params.enabled is True
    assert params.class_name == "document"
    assert params.margin == 5
    assert params.confidence_threshold == 0.7
    assert params.image_size == 640
