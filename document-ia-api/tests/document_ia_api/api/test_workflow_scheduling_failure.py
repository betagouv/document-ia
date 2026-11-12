"""Contrat HTTP d'acceptation lorsque la programmation échoue (issue #120 et #157).

Ces tests passent par les routes : ils vérifient le statut, le header
`Retry-After`, le corps RFC 7807 effectivement renvoyés au client, ainsi que
la suppression compensatoire immédiate des fichiers S3 orphelins (#157).
"""

import json
import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.redis.publisher import PublishFailedError, ReservationLostError


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

    def test_v1_execute_compensates_s3_and_returns_503_when_scheduling_fails(
        self, client_with_api_key_standard, standard_api_key_value, caplog
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_file_key_v1.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ) as close_execution,
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            with caplog.at_level(logging.INFO):
                response = client_with_api_key_standard.post(
                    "/api/v1/workflows/document-classification-v1/execute",
                    files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                    data={"metadata": json.dumps({"source": "test"})},
                    headers={"X-API-KEY": standard_api_key_value},
                )

        _assert_scheduling_unavailable(response)
        # L'exécution déjà persistée est clôturée, pas laissée en `STARTED`.
        close_execution.assert_awaited_once()
        # Compensation S3 immédiate : le fichier orphelin est supprimé
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)
        # Règle de sécurité : la clé S3 brute ne doit pas apparaître dans les logs
        assert raw_s3_key not in caplog.text
        assert "Compensated orphaned S3 upload for execution" in caplog.text

    def test_v2_execute_compensates_s3_and_returns_503_when_scheduling_fails(
        self, client_with_api_key_standard, standard_api_key_value, caplog
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_file_key_v2.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_v2_service.WorkflowV2Service.validateWorkflow",
                return_value=True,
            ),
            patch(
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
            ),
            patch(
                "document_ia_api.application.services.workflow_v2_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_v2_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ) as close_execution,
            patch(
                "document_ia_api.application.services.workflow_v2_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            with caplog.at_level(logging.INFO):
                response = client_with_api_key_standard.post(
                    "/api/v2/workflows/document-extraction-v2/execute",
                    files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                    data={"metadata": json.dumps({"source": "test"})},
                    headers={"X-API-KEY": standard_api_key_value},
                )

        _assert_scheduling_unavailable(response)
        close_execution.assert_awaited_once()
        # Compensation S3 immédiate : le fichier orphelin est supprimé
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)
        assert raw_s3_key not in caplog.text
        assert "Compensated orphaned S3 upload for execution" in caplog.text

    def test_v1_execute_compensates_s3_when_emit_workflow_started_fails(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_v1_emit_fail.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(side_effect=RuntimeError("DB write failed")),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v1/workflows/document-classification-v1/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)

    def test_v2_execute_compensates_s3_when_emit_workflow_started_fails(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_v2_emit_fail.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_v2_service.WorkflowV2Service.validateWorkflow",
                return_value=True,
            ),
            patch(
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
            ),
            patch(
                "document_ia_api.application.services.workflow_v2_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_v2_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(side_effect=RuntimeError("DB write failed")),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)

    def test_v2_execute_compensates_s3_when_reservation_is_lost(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_v2_reservation_lost.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_v2_service.WorkflowV2Service.validateWorkflow",
                return_value=True,
            ),
            patch(
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
            ),
            patch(
                "document_ia_api.application.services.workflow_v2_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_v2_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ) as close_execution,
            patch(
                "document_ia_api.application.services.workflow_v2_service.Publisher.publish_message",
                new=AsyncMock(side_effect=ReservationLostError("reservation_lost")),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 503
        assert 1 <= int(response.headers["Retry-After"]) <= 120
        body = response.json()
        assert body["errors"]["error"] == "idempotency_reservation_lost"
        close_execution.assert_awaited_once()
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)

    def test_v2_execute_with_file_url_does_not_call_s3_delete_on_failure(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        with (
            patch(
                "document_ia_api.application.services.workflow_v2_service.WorkflowV2Service.validateWorkflow",
                return_value=True,
            ),
            patch(
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
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_v2_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.workflow_v2_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={
                    "file_url": "https://example.com/remote.pdf",
                    "metadata": json.dumps({"source": "test"}),
                },
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        mock_s3_delete.assert_not_called()

    def test_s3_compensation_failure_does_not_mask_original_scheduling_error(
        self, client_with_api_key_standard, standard_api_key_value, caplog
    ):
        raw_s3_key = "uploads/2026/11/11/compensation_err.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(side_effect=RuntimeError("S3 completely unreachable")),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            with caplog.at_level(logging.WARNING):
                response = client_with_api_key_standard.post(
                    "/api/v1/workflows/document-classification-v1/execute",
                    files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                    data={"metadata": json.dumps({"source": "test"})},
                    headers={"X-API-KEY": standard_api_key_value},
                )

        # Must still return 503 without crashing or masking
        _assert_scheduling_unavailable(response)
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)
        assert "Failed to compensate S3 upload for execution" in caplog.text
        # Security: even on failure, raw S3 key must not appear
        assert raw_s3_key not in caplog.text

    def test_s3_compensation_when_delete_file_returns_false(
        self, client_with_api_key_standard, standard_api_key_value, caplog
    ):
        raw_s3_key = "uploads/2026/11/11/compensation_returns_false.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=False),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError("event_stream", "no_connection")
                ),
            ),
        ):
            with caplog.at_level(logging.INFO):
                response = client_with_api_key_standard.post(
                    "/api/v1/workflows/document-classification-v1/execute",
                    files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                    data={"metadata": json.dumps({"source": "test"})},
                    headers={"X-API-KEY": standard_api_key_value},
                )

        _assert_scheduling_unavailable(response)
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)
        assert "Failed to compensate S3 upload for execution" in caplog.text
        assert "(delete_file returned False)" in caplog.text
        assert "Compensated orphaned S3 upload for execution" not in caplog.text
        assert raw_s3_key not in caplog.text

    def test_v1_execute_compensates_s3_when_reservation_is_lost(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        raw_s3_key = "uploads/2026/11/11/sensitive_v1_reservation_lost.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ) as close_execution,
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(side_effect=ReservationLostError("reservation_lost")),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v1/workflows/document-classification-v1/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        assert response.status_code == 503
        assert 1 <= int(response.headers["Retry-After"]) <= 120
        body = response.json()
        assert body["errors"]["error"] == "idempotency_reservation_lost"
        close_execution.assert_awaited_once()
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)

    def test_execute_compensates_s3_when_idempotency_publish_finds_message_not_queued(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        raw_s3_key = "uploads/2026/11/11/unqueued_message_compensates.pdf"
        with (
            patch(
                "document_ia_api.application.services.workflow_service.workflow_repository.get_workflow_by_id",
                new=AsyncMock(return_value={"id": "document-classification-v1"}),
            ),
            patch(
                "document_ia_api.application.services.workflow_service.s3_service.upload_file",
                new=AsyncMock(
                    return_value={
                        "s3_key": raw_s3_key,
                        "presigned_url": "https://s3.example.com/p",
                    }
                ),
            ),
            patch(
                "document_ia_api.infra.s3_service.s3_service.delete_file",
                new=AsyncMock(return_value=True),
            ) as mock_s3_delete,
            patch(
                "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
                new=AsyncMock(),
            ),
            patch(
                "document_ia_api.application.services.execution_acceptance.EventStoreService.emit_workflow_failed",
                new=AsyncMock(),
            ) as close_execution,
            patch(
                "document_ia_api.application.services.workflow_service.Publisher.publish_message",
                new=AsyncMock(
                    side_effect=PublishFailedError(
                        "event_stream", "publication_not_queued"
                    )
                ),
            ),
        ):
            response = client_with_api_key_standard.post(
                "/api/v1/workflows/document-classification-v1/execute",
                files={"file": ("test.pdf", _pdf_file(), "application/pdf")},
                data={"metadata": json.dumps({"source": "test"})},
                headers={"X-API-KEY": standard_api_key_value},
            )

        _assert_scheduling_unavailable(response)
        close_execution.assert_awaited_once()
        mock_s3_delete.assert_awaited_once_with(raw_s3_key)
