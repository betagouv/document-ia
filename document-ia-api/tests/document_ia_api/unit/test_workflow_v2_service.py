from typing import Any
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from document_ia_api.api.contracts.workflow_v2 import WorkflowV2OverridePayload
from document_ia_api.application.services.workflow_v2_service import WorkflowV2Service
from document_ia_infra.data.workflow.dto.workflow_v2_dto import (
    LlmClassifyDocumentStepDto,
    LlmExtractDataStepDto,
)


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
                        "default": "openweight-medium",
                        "enum": ["openweight-medium", "albert-small"],
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


def test_resolve_workflow_configuration_merges_defaults_and_overrides(
    service: WorkflowV2Service,
):
    payload = WorkflowV2OverridePayload.model_validate(
        {
            "llm_extract_data": [
                {"param": "document_type", "value": "passeport"},
            ],
            "llm_classify_document": [
                {"param": "document_types", "value": ["cni"]},
            ],
        }
    )

    resolved = service._resolve_workflow_configuration(
        raw_workflow=_workflow_with_rules(),
        override_payload=payload,
    )

    assert resolved.id == "document-extraction-v2"
    classify = next(
        s for s in resolved.steps if isinstance(s, LlmClassifyDocumentStepDto)
    )
    extract = next(s for s in resolved.steps if isinstance(s, LlmExtractDataStepDto))
    assert isinstance(classify.params.document_types, list)
    assert extract.params.document_type is not None
    assert [document_type.value for document_type in classify.params.document_types] == [
        "cni"
    ]
    assert extract.params.model.value == "openweight-medium"
    assert extract.params.document_type.value == "passeport"


def test_resolve_workflow_configuration_merges_nested_preprocess_override(
    service: WorkflowV2Service,
):
    payload = WorkflowV2OverridePayload.model_validate(
        {
            "preprocess_file": [
                {
                    "param": "yoloworld",
                    "value": {"enabled": True, "class_name": "document"},
                }
            ],
            "llm_extract_data": [
                {"param": "document_type", "value": "cni"},
            ],
        }
    )
    raw_workflow = {
        **_workflow_with_rules(),
        "steps": [
            {
                "action": "preprocess_file",
                "params": {
                    "yoloworld": {
                        "type": "object",
                        "default": {
                            "enabled": False,
                            "class_name": "book",
                            "margin": 20,
                        },
                    }
                },
            },
            *_workflow_with_rules()["steps"],
        ],
    }

    resolved = service._resolve_workflow_configuration(
        raw_workflow=raw_workflow,
        override_payload=payload,
    )

    preprocess = resolved.steps[0].params.yoloworld
    assert preprocess.enabled is True
    assert preprocess.model_dump().get("model") is None
    assert preprocess.class_name == "document"
    assert preprocess.margin == 20


@pytest.mark.asyncio
async def test_execute_workflow_emits_started_event_with_workflow_configuration(
    monkeypatch: pytest.MonkeyPatch,
):
    db_session = AsyncMock()
    service = WorkflowV2Service(db_session)

    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
        lambda _: _workflow_with_rules(),
    )

    publish_mock = AsyncMock(return_value="1-0")
    monkeypatch.setattr(service.redis_producer, "publish_message", publish_mock)

    event_store_instance = MagicMock()
    event_store_instance.emit_workflow_started = AsyncMock()
    monkeypatch.setattr(
        "document_ia_api.application.services.workflow_v2_service.EventStoreService",
        lambda _: event_store_instance,
    )

    payload = WorkflowV2OverridePayload.model_validate(
        {"llm_extract_data": [{"param": "document_type", "value": "cni"}]}
    )

    result = await service.execute_workflow(
        organization_id=uuid4(),
        workflow_id="document-extraction-v2",
        file=None,
        file_url="https://example.com/document.pdf",
        metadata_json='{"source":"api"}',
        override_payload=payload,
    )

    assert result.workflow_id == "document-extraction-v2"
    assert result.workflow_configuration.id == "document-extraction-v2"

    _, kwargs = event_store_instance.emit_workflow_started.call_args
    assert kwargs["workflow_configuration"].id == "document-extraction-v2"
    assert kwargs["workflow_configuration"].steps
    assert kwargs["event_version"] == 2


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
