"""Golden payloads captured from the parent e54d117, not the new decoder."""

import copy
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from document_ia_api.application.services.execution_service import ExecutionService
from document_ia_api.infra.webhook_notification_service import (
    WebhookNotificationService,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.schema.mappers import event_mapper


ROOT = Path(__file__).parents[4]
FIXTURES = json.loads(
    (ROOT / "document-ia-infra/tests/fixtures/persisted_events.json").read_text()
)
EXPECTED = json.loads(
    (
        ROOT / "document-ia-api/tests/fixtures/execution_payloads_before_decoder.json"
    ).read_text()
)


def event_dto(name):
    payload = copy.deepcopy(FIXTURES["common"] | FIXTURES["events"][name])
    return EventDTO(
        id=UUID(payload["event_id"]),
        workflow_id=payload["workflow_id"],
        organization_id=UUID(payload["organization_id"]),
        execution_id=payload["execution_id"],
        created_at=datetime.fromisoformat(payload["created_at"]),
        event_type=EventType(payload["event_type"]),
        event=payload,
    )


@pytest.mark.parametrize("name", EXPECTED)
@pytest.mark.parametrize("debug", [False, True])
def test_response_matches_pre_refactor_payload(name, debug, monkeypatch):
    decoder = MagicMock(wraps=event_mapper.convert_inner_event_dto)
    monkeypatch.setattr(
        "document_ia_api.application.services.execution_service.convert_inner_event_dto",
        decoder,
    )
    dto = event_dto(name)
    response = ExecutionService().get_event_model(dto, dto.execution_id, debug)
    assert response.model_dump(mode="json") == EXPECTED[name][str(debug).lower()]
    decoder.assert_called_once_with(dto.event, dto.event_type)


@pytest.mark.parametrize("name", EXPECTED)
async def test_notification_matches_pre_refactor_non_debug_payload(name, monkeypatch):
    dto = event_dto(name)
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=200))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "document_ia_api.infra.webhook_notification_service.httpx.AsyncClient",
        MagicMock(return_value=context),
    )
    webhook = SimpleNamespace(
        url="https://example.com/webhook", headers={"X-Test": "fixture"}
    )
    await WebhookNotificationService()._call_webhook_notification(webhook, dto)
    client.post.assert_awaited_once()
    args, kwargs = client.post.call_args
    assert args == (webhook.url,)
    assert kwargs["headers"] == {
        "X-Test": "fixture",
        "Content-Type": "application/json",
    }
    assert json.loads(kwargs["content"]) == EXPECTED[name]["false"]


def test_step_event_is_still_rejected_before_payload_validation():
    dto = event_dto("step_completed_v1")
    dto.event = {}
    with pytest.raises(HTTPException) as error:
        ExecutionService().get_event_model(dto, dto.execution_id, False)
    assert error.value.status_code == 400
    assert error.value.detail == "Event type not supported"


@pytest.mark.parametrize("name", ["started_v1", "completed_v1", "failed_v1"])
def test_invalid_supported_payload_keeps_pydantic_validation_error(name):
    dto = event_dto(name)
    dto.event = {}
    with pytest.raises(ValidationError):
        ExecutionService().get_event_model(dto, dto.execution_id, False)
