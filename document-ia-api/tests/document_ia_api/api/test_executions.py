from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from uuid import uuid4

import pytest

from document_ia_api.api.exceptions.entity_not_found_exception import (
    EntityNotFoundException,
)
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType


class TestExecutions:
    @pytest.fixture
    def execution_id(self):
        return "exec_test_123"

    def _event_dto_started(self, execution_id: str) -> EventDTO:
        created = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        event_payload = {
            "workflow_id": "document-analysis-v1",
            "execution_id": execution_id,
            "created_at": created.isoformat(),
            "file_info": {
                "filename": "test.pdf",
                "s3_key": "uploads/test.pdf",
                "size": 1024,
                "content_type": "application/pdf",
                "uploaded_at": created.isoformat(),
                "presigned_url": "https://example.com/presigned",
            },
            "metadata": {"source": "email"},
            "version": 1,
        }
        return EventDTO(
            id=uuid4(),
            workflow_id="document-analysis-v1",
            execution_id=execution_id,
            created_at=created,
            event_type=EventType.WORKFLOW_EXECUTION_STARTED,
            event=event_payload,
            version=1,
        )

    def _event_dto_completed(self, execution_id: str) -> EventDTO:
        created = datetime(2024, 1, 15, 10, 31, tzinfo=timezone.utc)
        event_payload = {
            "workflow_id": "document-analysis-v1",
            "execution_id": execution_id,
            "created_at": created.isoformat(),
            "final_result": {
                "document_type": "cni",
                "confidence": 0.9,
                "explanation": "blabla",
            },
            "total_processing_time_ms": 1200,
            "output_summary": {},
            "steps_completed": 4,
            "version": 1,
        }
        return EventDTO(
            id=uuid4(),
            workflow_id="document-analysis-v1",
            execution_id=execution_id,
            created_at=created,
            event_type=EventType.WORKFLOW_EXECUTION_COMPLETED,
            event=event_payload,
            version=1,
        )

    def test_get_execution_pending_success(
            self, client_with_api_key, valid_api_key, execution_id
    ):
        async def fake_get_last_event(execution_id_param: str):
            return self._event_dto_started(execution_id_param)

        with patch(
                "document_ia_api.application.services.event_store_service."
                "EventStoreService.get_last_event_for_execution_id",
                new=AsyncMock(side_effect=fake_get_last_event),
        ):
            response = client_with_api_key.get(
                f"/api/v1/executions/{execution_id}",
                headers={"X-API-KEY": valid_api_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == execution_id
        assert data["status"] == "PENDING"
        assert data["data"]["file_name"] == "test.pdf"
        assert data["data"]["content_type"] == "application/pdf"
        assert "presigned_url" in data["data"]
        assert "created_at" in data["data"]

    def test_get_execution_done_success(
            self, client_with_api_key, valid_api_key, execution_id
    ):
        async def fake_get_last_event(execution_id_param: str):
            return self._event_dto_completed(execution_id_param)

        with patch(
                "document_ia_api.application.services.event_store_service."
                "EventStoreService.get_last_event_for_execution_id",
                new=AsyncMock(side_effect=fake_get_last_event),
        ):
            response = client_with_api_key.get(
                f"/api/v1/executions/{execution_id}",
                headers={"X-API-KEY": valid_api_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == execution_id
        assert data["status"] == "DONE"
        assert data["data"]["total_processing_time_ms"] == 1200
        assert data["data"]["result"]["document_type"] == "cni"
        assert data["data"]["result"]["confidence"] == 0.9
        assert data["data"]["result"]["explanation"] == "blabla"

    def test_get_execution_not_found(
            self, client_with_api_key, valid_api_key, execution_id
    ):
        with patch(
                "document_ia_api.application.services.event_store_service."
                "EventStoreService.get_last_event_for_execution_id",
                new=AsyncMock(side_effect=EntityNotFoundException("execution", execution_id)),
        ):
            response = client_with_api_key.get(
                f"/api/v1/executions/{execution_id}",
                headers={"X-API-KEY": valid_api_key},
            )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "entity_not_found"

    def test_get_execution_internal_error(
            self, client_with_api_key, valid_api_key, execution_id
    ):
        with patch(
                "document_ia_api.application.services.event_store_service."
                "EventStoreService.get_last_event_for_execution_id",
                new=AsyncMock(side_effect=Exception("db down")),
        ):
            response = client_with_api_key.get(
                f"/api/v1/executions/{execution_id}",
                headers={"X-API-KEY": valid_api_key},
            )

        assert response.status_code == 500
        body = response.json()
        assert body["detail"] == "db down"

    def test_get_execution_missing_api_key(self, client_without_api_key, execution_id):
        response = client_without_api_key.get(f"/api/v1/executions/{execution_id}")
        assert response.status_code == 403

    def test_get_execution_invalid_api_key(
            self, client_with_api_key, execution_id
    ):
        response = client_with_api_key.get(
            f"/api/v1/executions/{execution_id}",
            headers={"X-API-KEY": "invalid-api-key"},
        )
        assert response.status_code == 401
