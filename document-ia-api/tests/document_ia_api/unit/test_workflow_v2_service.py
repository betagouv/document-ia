from typing import Any

import pytest
from fastapi import HTTPException

from document_ia_api.api.contracts.workflow_v2 import WorkflowV2OverridePayload
from document_ia_api.application.services.workflow_v2_service import WorkflowV2Service


@pytest.fixture
def service() -> WorkflowV2Service:
    return WorkflowV2Service()


def _workflow_with_rules() -> dict[str, Any]:
    return {
        "id": "document-extraction-v2",
        "steps": [
            {
                "action": "llm_extract_data",
                "params": {
                    # Required (no default): must be overridden.
                    "document_type": {
                        "type": "string",
                        "enum": ["cni", "passeport"],
                    },
                    # Optional (has default)
                    "model": {
                        "type": "string",
                        "default": "albert-large",
                        "enum": ["albert-large", "albert-small"],
                    },
                },
            },
            {
                "action": "llm_classify_document",
                "params": {
                    "document_types": {
                        "default": "all",
                        "oneOf": [
                            {"type": "string", "enum": ["all"]},
                            {
                                "type": "array",
                                "items": {"type": "string", "enum": ["cni", "passeport"]},
                            },
                        ],
                    }
                },
            },
        ],
    }


def _workflow_with_defaults_only() -> dict[str, Any]:
    return {
        "id": "document-defaults-v2",
        "steps": [
            {
                "action": "extract_content_ocr",
                "params": {
                    "model": {
                        "type": "string",
                        "default": "mistral",
                        "enum": ["mistral", "azure"],
                    }
                },
            },
            {
                "action": "llm_extract_data",
                "params": {
                    "temperature": {
                        "type": "float",
                        "default": 0.0,
                    }
                },
            },
        ],
    }


def test_validate_workflow_success(monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    payload = WorkflowV2OverridePayload.model_validate(
        {"llm_extract_data": [{"param": "document_type", "value": "cni"}]}
    )

    assert service.validateWorkflow("document-extraction-v2", payload) is True


def test_validate_workflow_raises_404_when_workflow_not_found(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: None,
    )

    payload = WorkflowV2OverridePayload.model_validate({})

    with pytest.raises(HTTPException) as exc_info:
        service.validateWorkflow("unknown", payload)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"] == "entity_not_found"


def test_validate_workflow_raises_when_step_not_found(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    payload = WorkflowV2OverridePayload.model_validate(
        {"step_inconnue": [{"param": "document_type", "value": "cni"}]}
    )

    with pytest.raises(HTTPException) as exc_info:
        service.validateWorkflow("document-extraction-v2", payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["step"] == "step_inconnue"
    assert exc_info.value.detail["param"] is None


def test_validate_workflow_raises_when_param_not_configurable(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    payload = WorkflowV2OverridePayload.model_validate(
        {"llm_extract_data": [{"param": "does_not_exist", "value": "x"}]}
    )

    with pytest.raises(HTTPException) as exc_info:
        service.validateWorkflow("document-extraction-v2", payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["step"] == "llm_extract_data"
    assert exc_info.value.detail["param"] == "does_not_exist"


def test_validate_workflow_raises_when_required_param_missing(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    payload = WorkflowV2OverridePayload.model_validate({})

    with pytest.raises(HTTPException) as exc_info:
        service.validateWorkflow("document-extraction-v2", payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["step"] == "llm_extract_data"
    assert exc_info.value.detail["param"] == "document_type"


def test_validate_workflow_raises_when_one_of_value_is_invalid(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    payload = WorkflowV2OverridePayload.model_validate(
        {
            "llm_extract_data": [{"param": "document_type", "value": "cni"}],
            "llm_classify_document": [{"param": "document_types", "value": ["cni", "foo"]}],
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        service.validateWorkflow("document-extraction-v2", payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["step"] == "llm_classify_document"
    assert exc_info.value.detail["param"] == "document_types"


def test_validate_workflow_accepts_no_override_when_all_params_have_defaults(
    monkeypatch: pytest.MonkeyPatch, service: WorkflowV2Service
):
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_defaults_only(),
    )

    assert service.validateWorkflow("document-defaults-v2", None) is True
