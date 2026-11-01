"""Contrat HTTP d'acceptation lorsque la programmation échoue (issue #120).

Ces tests passent par les routes : ils vérifient le statut, le header
`Retry-After` et le corps RFC 7807 effectivement renvoyés au client.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.redis.publisher import PublishFailedError


def _pdf_file() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"


def _assert_scheduling_unavailable(response):
    assert response.status_code == 503
    assert 1 <= int(response.headers["Retry-After"]) <= 120
    body = response.json()
    assert body["errors"]["error"] == "execution_scheduling_unavailable"
    # L'identifiant est exposé pour le diagnostic, mais l'exécution n'est pas
    # annoncée comme acceptée : aucune donnée `processing` n'est retournée.
    assert "data" not in body
    assert body["errors"]["execution_id"]


class TestWorkflowExecutionSchedulingFailure:
    @pytest.fixture
    async def organization_id(self):
        yield uuid4()

    def test_v1_execute_returns_503_when_scheduling_fails(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        with patch(
            "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
            new=AsyncMock(return_value={"id": "document-classification-v1"}),
        ), patch(
            "document_ia_api.application.services.workflow_service.s3_service.upload_file",
            new=AsyncMock(return_value={"s3_key": "k", "presigned_url": "u"}),
        ), patch(
            "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
            new=AsyncMock(),
        ), patch(
            "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
            new=AsyncMock(),
        ) as close_execution, patch(
            "document_ia_api.application.services.workflow_service.Publisher.publish_message",
            new=AsyncMock(side_effect=PublishFailedError("event_stream", "no_connection")),
        ):
            response = client_with_api_key_standard.post(
                "/api/v1/workflows/document-classification-v1/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        # L'exécution déjà persistée est clôturée, pas laissée en `STARTED`.
        close_execution.assert_awaited_once()

    def test_v2_execute_returns_503_when_scheduling_fails(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        with patch(
            "document_ia_api.application.services.workflow_v2_service.WorkflowV2Service.validateWorkflow",
            return_value=True,
        ), patch(
            "document_ia_api.application.services.workflow_v2_service.workflow_v2_repository.get_raw_workflow_by_id",
            return_value={
                "id": "document-extraction-v2",
                "steps": [
                    {
                        "action": "llm_classify_document",
                        "params": {"document_types": {"default": "all"}},
                    }
                ],
            },
        ), patch(
            "document_ia_api.application.services.workflow_v2_service.s3_service.upload_file",
            new=AsyncMock(return_value={"s3_key": "k", "presigned_url": "u"}),
        ), patch(
            "document_ia_api.application.services.workflow_v2_service.EventStoreService.emit_workflow_started",
            new=AsyncMock(),
        ), patch(
            "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
            new=AsyncMock(),
        ) as close_execution, patch(
            "document_ia_api.application.services.workflow_v2_service.Publisher.publish_message",
            new=AsyncMock(side_effect=PublishFailedError("event_stream", "no_connection")),
        ):
            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        close_execution.assert_awaited_once()
