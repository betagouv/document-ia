import io
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from httpx import ASGITransport
import pytest
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError

from document_ia_infra.redis.redis_settings import redis_settings

from document_ia_api.api.middleware.execution_admission import check_execution_admission
import document_ia_api.api.middleware.rate_limiting_middleware as rl_mod
from document_ia_api.core.idempotency.models import (
    IdempotencyEntry,
    IdempotencyStatus,
)
from document_ia_api.core.idempotency.request_fingerprint import (
    compute_request_fingerprint,
)
from document_ia_api.infra.idempotency_service import build_idempotency_redis_key
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.repository.organization_repository import (
    OrganizationRepository,
)
from document_ia_infra.redis.publisher import (
    PublishFailedError,
    ReservationLostError,
)
from tests.document_ia_api.conftest import create_test_app


@pytest.fixture
def mock_pdf_file():
    pdf_content = (
        b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
    )
    return io.BytesIO(pdf_content)


@pytest.fixture
def mock_pdf_file_different():
    pdf_content = (
        b"%PDF-1.4\n2 0 obj\n<<\n/Type /Catalog /Pages 3 0 R\n>>\nendobj\n"
    )
    return io.BytesIO(pdf_content)


@pytest.fixture(autouse=True)
def use_test_redis(monkeypatch: pytest.MonkeyPatch, redis_client: Redis) -> None:
    from document_ia_infra.redis import redis_manager as redis_manager_module

    async def get_connection() -> Redis:
        return redis_client

    monkeypatch.setattr(
        redis_manager_module.redis_manager, "get_connection", get_connection
    )


@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    connection = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        db=redis_settings.REDIS_DB,
        password=redis_settings.REDIS_PASSWORD.get_secret_value(),
        decode_responses=True,
    )
    try:
        await connection.ping()
    except AuthenticationError as exc:
        if "without any password configured" not in str(exc):
            raise
        await connection.aclose()
        connection = Redis(
            host=redis_settings.REDIS_HOST,
            port=redis_settings.REDIS_PORT,
            db=redis_settings.REDIS_DB,
            decode_responses=True,
        )
        await connection.ping()
    try:
        yield connection
    finally:
        await connection.aclose()


@pytest.fixture(autouse=True)
def mock_publish_success():
    """Default mocked publish for success scenarios in integration tests.

    Idempotent requests publish through the ownership-fenced path, so both the
    plain and the fenced publisher must be stubbed.
    """
    with patch(
        "document_ia_api.application.services.workflow_service.Publisher.publish_message",
        new=AsyncMock(return_value="1-0"),
    ), patch(
        "document_ia_api.application.services.workflow_v2_service.Publisher.publish_message",
        new=AsyncMock(return_value="1-0"),
    ), patch(
        "document_ia_infra.redis.publisher.Publisher.publish_message_fenced",
        new=AsyncMock(return_value="1-0"),
    ):
        yield


@pytest.fixture
async def async_client(
    isolated_database_manager,
    mock_redis_service,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Single-event-loop ASGI test client avoiding cross-request asyncpg pool issues."""
    from document_ia_api.api import auth as auth_mod
    from document_ia_api.api.routes.v1 import workflow as v1_wf_mod
    from document_ia_api.api.routes.v2 import workflow as v2_wf_mod

    app = create_test_app()
    app.dependency_overrides[check_execution_admission] = lambda: None
    app.dependency_overrides[v2_wf_mod.database_manager.async_get_db] = (
        isolated_database_manager.async_get_db
    )
    app.dependency_overrides[v1_wf_mod.database_manager.async_get_db] = (
        isolated_database_manager.async_get_db
    )
    app.dependency_overrides[auth_mod.database_manager.async_get_db] = (
        isolated_database_manager.async_get_db
    )
    original = rl_mod.redis_service
    rl_mod.redis_service = mock_redis_service

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        try:
            yield client
        finally:
            rl_mod.redis_service = original


class TestIdempotencyIntegration:
    """Integration tests for Idempotency-Key support across v1 and v2 workflow endpoints."""

    @pytest.mark.asyncio
    async def test_v2_execute_idempotent_replay(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        idempotency_key = f"key-v2-replay-{uuid4()}"
        file_url = "https://example.com/contract.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        metadata = json.dumps({"source": "integration_test", "doc_type": "contract"})

        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }
        payload = {
            "file_url": file_url,
            "override": override,
            "metadata": metadata,
        }

        # 1. First submission (Miss)
        response_1 = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data=payload,
            headers=headers,
        )
        assert response_1.status_code == 200
        data_1 = response_1.json()
        assert data_1["status"] == "success"
        execution_id_1 = data_1["data"]["execution_id"]
        assert execution_id_1
        assert "Idempotent-Replay" not in response_1.headers

        # 2. Second submission with exact same key and payload (Replay Hit)
        response_2 = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data=payload,
            headers=headers,
        )
        assert response_2.status_code == 200
        assert response_2.headers.get("Idempotent-Replay") == "true"
        data_2 = response_2.json()
        assert data_2["status"] == "success"
        assert data_2["data"]["execution_id"] == execution_id_1
        assert data_2["data"]["workflow_id"] == "document-extraction-v2"
        assert data_2["data"]["status"] == "processing"

    @pytest.mark.asyncio
    async def test_v2_execute_idempotency_conflict(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        idempotency_key = f"key-v2-conflict-{uuid4()}"
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})

        # First submission with url A
        resp_1 = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": "https://example.com/docA.pdf", "override": override},
            headers=headers,
        )
        assert resp_1.status_code == 200

        # Second submission with same key but different url B
        resp_2 = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": "https://example.com/docB.pdf", "override": override},
            headers=headers,
        )
        assert resp_2.status_code == 409
        body = resp_2.json()
        assert body["code"] == "http.conflict"
        assert body["errors"]["error"] == "idempotency_conflict"

    @pytest.mark.asyncio
    async def test_v2_execute_idempotency_in_progress(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
        organization_id,
    ):
        idempotency_key = f"key-v2-inprog-{uuid4()}"
        workflow_id = "document-extraction-v2"
        file_url = "https://example.com/pending.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})

        # Compute matching fingerprint
        fp = await compute_request_fingerprint(
            method="POST",
            path=f"/api/v2/workflows/{workflow_id}/execute",
            file_url=file_url,
            params={"override": override, "metadata": None},
        )

        reserved_exec_id = f"exec-in-flight-{uuid4()}"
        redis_key = build_idempotency_redis_key(
            version=2,
            organization_id=organization_id,
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
        )

        # Place key in Redis with IN_PROGRESS state
        redis = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
        try:
            entry = IdempotencyEntry(
                fingerprint=fp,
                execution_id=reserved_exec_id,
                status=IdempotencyStatus.IN_PROGRESS,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await redis.set(redis_key, entry.model_dump_json(), ex=60)
        finally:
            await redis.aclose()

        # Concurrent request with same key
        response = await async_client.post(
            f"/api/v2/workflows/{workflow_id}/execute",
            data={"file_url": file_url, "override": override},
            headers={
                "X-API-KEY": standard_api_key_value,
                "Idempotency-Key": idempotency_key,
            },
        )
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "http.conflict"
        assert body["errors"]["error"] == "idempotency_in_progress"
        assert body["errors"]["execution_id"] == reserved_exec_id

    @pytest.mark.asyncio
    async def test_v2_execute_invalid_idempotency_key_format(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        # Empty string
        resp_empty = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": "https://example.com/doc.pdf"},
            headers={
                "X-API-KEY": standard_api_key_value,
                "Idempotency-Key": "",
            },
        )
        assert resp_empty.status_code == 400
        assert resp_empty.json()["errors"]["error"] == "invalid_idempotency_key"

        # Key too long (257 chars)
        resp_long = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": "https://example.com/doc.pdf"},
            headers={
                "X-API-KEY": standard_api_key_value,
                "Idempotency-Key": "x" * 257,
            },
        )
        assert resp_long.status_code == 400
        assert resp_long.json()["errors"]["error"] == "invalid_idempotency_key"

    @pytest.mark.asyncio
    async def test_v1_execute_idempotent_replay_and_conflict(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
        mock_pdf_file,
        mock_pdf_file_different,
    ):
        idempotency_key = f"key-v1-{uuid4()}"
        workflow_id = "document-classification-v1"
        metadata = json.dumps({"source": "v1_test"})

        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        # 1. First submission (Miss)
        resp_1 = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/execute",
            files={"file": ("doc.pdf", mock_pdf_file.getvalue(), "application/pdf")},
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp_1.status_code == 200
        data_1 = resp_1.json()
        exec_id_1 = data_1["data"]["execution_id"]
        assert "Idempotent-Replay" not in resp_1.headers

        # 2. Replay with exact same file content
        resp_2 = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/execute",
            files={"file": ("doc.pdf", mock_pdf_file.getvalue(), "application/pdf")},
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp_2.status_code == 200
        assert resp_2.headers.get("Idempotent-Replay") == "true"
        data_2 = resp_2.json()
        assert data_2["data"]["execution_id"] == exec_id_1

        # 3. Conflict with different file content
        resp_conflict = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/execute",
            files={"file": ("doc.pdf", mock_pdf_file_different.getvalue(), "application/pdf")},
            data={"metadata": metadata},
            headers=headers,
        )
        assert resp_conflict.status_code == 409
        body_conflict = resp_conflict.json()
        assert body_conflict["code"] == "http.conflict"
        assert body_conflict["errors"]["error"] == "idempotency_conflict"

    @pytest.mark.asyncio
    async def test_early_release_on_publish_failure_allows_immediate_retry(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        idempotency_key = f"key-release-fail-{uuid4()}"
        file_url = "https://example.com/retry_after_failure.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})

        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        # 1. First request fails during stream publish
        with patch(
            "document_ia_infra.redis.publisher.Publisher.publish_message_fenced",
            new=AsyncMock(side_effect=PublishFailedError("event_stream", "simulated_broker_down")),
        ):
            resp_fail = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )
            assert resp_fail.status_code == 503
            assert resp_fail.headers.get("Retry-After") is not None

        # 2. The key should have been released immediately, so immediate retry succeeds
        resp_retry = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": file_url, "override": override},
            headers=headers,
        )
        assert resp_retry.status_code == 200
        data_retry = resp_retry.json()
        assert data_retry["status"] == "success"
        assert data_retry["data"]["execution_id"]

    @pytest.mark.asyncio
    async def test_accepted_execution_survives_completion_tracking_failure(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        """A Redis tracking failure must not turn an accepted execution into an error.

        The started event is persisted and the message published before
        completion tracking runs, so releasing the key or returning 5xx would let
        a retry schedule a duplicate execution.
        """
        idempotency_key = f"key-tracking-fail-{uuid4()}"
        file_url = "https://example.com/tracking_failure.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        # Every completion write fails, so nothing is recorded for the accepted
        # execution. The request must still succeed, and the execution must not
        # be scheduled twice.
        with patch(
            "document_ia_api.infra.idempotency_service.IdempotencyService.complete_or_retain",
            new=AsyncMock(side_effect=RuntimeError("redis unreachable")),
        ):
            response = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )

        assert response.status_code == 200
        execution_id = response.json()["data"]["execution_id"]
        assert execution_id

        # A retry with the same key may either replay the accepted execution or,
        # if nothing could be recorded, be refused as in progress. What it must
        # never do is return 200 with a different execution.
        replay = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": file_url, "override": override},
            headers=headers,
        )
        if replay.status_code == 200:
            assert replay.json()["data"]["execution_id"] == execution_id
        else:
            assert replay.status_code == 409
            assert replay.json()["errors"]["error"] == "idempotency_in_progress"
            assert replay.json()["errors"]["execution_id"] == execution_id

    @pytest.mark.asyncio
    async def test_lost_reservation_blocks_duplicate_publication(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        """A reservation lost before publication must not publish an execution."""
        idempotency_key = f"key-lost-reservation-{uuid4()}"
        file_url = "https://example.com/lost_reservation.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        with patch(
            "document_ia_infra.redis.publisher.Publisher.publish_message_fenced",
            new=AsyncMock(side_effect=ReservationLostError()),
        ) as publish:
            response = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )

        assert response.status_code == 503
        assert response.json()["errors"]["error"] == "idempotency_reservation_lost"
        # The fence lives inside the publication call, which reported that the
        # reservation was lost and wrote nothing to the stream.
        publish.assert_awaited_once()
        publish.await_args.kwargs["reservation_execution_id"]
        # The reply must not announce an accepted execution.
        assert "data" not in response.json()

    @pytest.mark.asyncio
    async def test_lost_reservation_closes_started_execution(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
        isolated_database_manager,
    ):
        """The started event is committed before publication, so losing the
        reservation afterwards must close the execution instead of leaving it
        permanently `STARTED` with nothing to advance it."""
        idempotency_key = f"key-lost-closed-{uuid4()}"
        file_url = "https://example.com/lost_closed.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        with patch(
            "document_ia_infra.redis.publisher.Publisher.publish_message_fenced",
            new=AsyncMock(side_effect=ReservationLostError()),
        ):
            response = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )

        assert response.status_code == 503
        execution_id = response.json()["errors"]["execution_id"]
        assert execution_id

        # The abandoned execution must be terminal, never a lingering STARTED.
        from document_ia_infra.service.event_store_service import EventStoreService

        async with isolated_database_manager.local_session() as session:
            events = await EventStoreService(session).get_events_by_execution_id(
                execution_id
            )

        from document_ia_infra.data.event.dto.event_type_enum import EventType

        event_types = [event.event_type for event in events]
        assert EventType.WORKFLOW_EXECUTION_STARTED in event_types
        assert events[-1].event_type == EventType.WORKFLOW_EXECUTION_FAILED
        assert events[-1].event.error_type == "idempotency_reservation_lost"

    @pytest.mark.asyncio
    async def test_capacity_rejection_releases_the_new_reservation(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        """A capacity refusal must not leave the key reserved.

        The reservation is created before the preflight; if it is not released,
        every retry with the same key gets `idempotency_in_progress` until the
        lock expires, pointing at an execution that was never persisted.
        """
        from document_ia_infra.redis.admission import AdmissionUnavailableError

        idempotency_key = f"key-capacity-release-{uuid4()}"
        file_url = "https://example.com/capacity_release.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        with patch(
            "document_ia_api.api.middleware.execution_admission.admit_execution",
            new=AsyncMock(side_effect=AdmissionUnavailableError("full")),
        ):
            refused = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )
        assert refused.status_code == 503
        assert refused.json()["errors"]["error"] == "execution_capacity_unavailable"

        # Capacity recovered: the same key must be accepted immediately, not
        # rejected as in-progress on a reservation that protects nothing.
        accepted = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": file_url, "override": override},
            headers=headers,
        )
        assert accepted.status_code == 200
        assert accepted.json()["data"]["execution_id"]

    @pytest.mark.asyncio
    async def test_replay_is_served_while_capacity_is_saturated(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
    ):
        """An accepted request must be replayable even when the queue is full.

        Replay needs no queue capacity, so a saturated queue must not hide an
        execution the client already scheduled.
        """
        from document_ia_infra.redis.admission import AdmissionUnavailableError

        idempotency_key = f"key-capacity-replay-{uuid4()}"
        file_url = "https://example.com/capacity_replay.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        first = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": file_url, "override": override},
            headers=headers,
        )
        assert first.status_code == 200
        accepted_id = first.json()["data"]["execution_id"]

        with patch(
            "document_ia_api.api.middleware.execution_admission.admit_execution",
            new=AsyncMock(side_effect=AdmissionUnavailableError("full")),
        ):
            replay = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers=headers,
            )

        assert replay.status_code == 200
        assert replay.headers.get("Idempotent-Replay") == "true"
        assert replay.json()["data"]["execution_id"] == accepted_id

        # A new submission still meets the saturated queue.
        with patch(
            "document_ia_api.api.middleware.execution_admission.admit_execution",
            new=AsyncMock(side_effect=AdmissionUnavailableError("full")),
        ):
            fresh = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url + "?new=1", "override": override},
                headers={
                    "X-API-KEY": standard_api_key_value,
                    "Idempotency-Key": f"key-capacity-fresh-{uuid4()}",
                },
            )

        assert fresh.status_code == 503
        assert fresh.json()["errors"]["error"] == "execution_capacity_unavailable"

    @pytest.mark.asyncio
    async def test_cross_organization_isolation(
        self,
        async_client: httpx.AsyncClient,
        isolated_database_manager,
        standard_api_key_value: str,
        monkeypatch,
    ):
        idempotency_key = f"shared-key-{uuid4()}"
        file_url = "https://example.com/shared.pdf"
        override = json.dumps({"llm_extract_data": [{"param": "document_type", "value": "cni"}]})

        # Request from Organization 1
        resp_org1 = await async_client.post(
            "/api/v2/workflows/document-extraction-v2/execute",
            data={"file_url": file_url, "override": override},
            headers={
                "X-API-KEY": standard_api_key_value,
                "Idempotency-Key": idempotency_key,
            },
        )
        assert resp_org1.status_code == 200
        exec_id_org1 = resp_org1.json()["data"]["execution_id"]

        # Persist organization 2 in PostgreSQL to satisfy the foreign key constraint
        async with isolated_database_manager.local_session() as session:
            repo = OrganizationRepository(session)
            org2_db = await repo.create(
                contact_email=f"org2-{uuid4().hex[:8]}@example.org",
                name=f"Org 2 {uuid4().hex[:6]}",
                platform_role=PlatformRole.STANDARD,
            )
            await session.commit()
            org2_id = org2_db.id

        try:
            # Now mock organization 2 for auth
            from document_ia_api.api import auth as auth_mod

            now = datetime.now(timezone.utc)
            org2 = OrganizationDTO(
                id=org2_id,
                contact_email="org2@example.org",
                name="Org 2",
                platform_role=PlatformRole.STANDARD,
                created_at=now,
                updated_at=now,
            )
            api_key_org2 = ApiKeyDTO(
                id=uuid4(),
                organization_id=org2.id,
                organization=org2,
                key_hash="hash",
                prefix="KEYORG2X",
                status=ApiKeyStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )

            async def fake_get_api_key(self, presented: str):
                return api_key_org2

            monkeypatch.setattr(auth_mod.ApiKeyService, "get_from_presented_key", fake_get_api_key)

            # Request from Organization 2 with the same idempotency key
            resp_org2 = await async_client.post(
                "/api/v2/workflows/document-extraction-v2/execute",
                data={"file_url": file_url, "override": override},
                headers={
                    "X-API-KEY": standard_api_key_value,
                    "Idempotency-Key": idempotency_key,
                },
            )
            assert resp_org2.status_code == 200
            exec_id_org2 = resp_org2.json()["data"]["execution_id"]

            # Must be two distinct executions isolated per organization!
            assert exec_id_org1 != exec_id_org2
        finally:
            async with isolated_database_manager.local_session() as session:
                repo = OrganizationRepository(session)
                try:
                    await repo.delete(org2_id)
                    await session.commit()
                except Exception:
                    await session.rollback()


class TestStartEventIsMandatory:
    """A published execution must always have a start event to replay from.

    v1 used to swallow failures from emit_workflow_started and publish anyway.
    The client got 200, the retry got 404 ("execution not found for replay"), and
    the attempt after that scheduled the work again.
    """

    @pytest.mark.asyncio
    async def test_v1_does_not_publish_when_the_start_event_fails(
        self,
        async_client: httpx.AsyncClient,
        standard_api_key_value: str,
        mock_pdf_file,
    ):
        idempotency_key = f"key-start-fail-{uuid4()}"
        headers = {
            "X-API-KEY": standard_api_key_value,
            "Idempotency-Key": idempotency_key,
        }

        with patch(
            "document_ia_api.application.services.workflow_service.EventStoreService.emit_workflow_started",
            new=AsyncMock(side_effect=RuntimeError("database is down")),
        ) as emit, patch(
            "document_ia_infra.redis.publisher.Publisher.publish_message_fenced",
            new=AsyncMock(return_value="1-0"),
        ) as publish:
            response = await async_client.post(
                "/api/v1/workflows/document-classification-v1/execute",
                files={"file": ("doc.pdf", mock_pdf_file.getvalue(), "application/pdf")},
                data={"metadata": json.dumps({"source": "start_fail"})},
                headers=headers,
            )

        emit.assert_awaited_once()
        # Nothing was scheduled, so the caller must not be told it was accepted.
        assert response.status_code == 503
        assert response.json()["errors"]["error"] == "execution_scheduling_unavailable"
        publish.assert_not_awaited()

        # The reservation was released, so the client can retry with the same key.
        retry = await async_client.post(
            "/api/v1/workflows/document-classification-v1/execute",
            files={"file": ("doc.pdf", mock_pdf_file.getvalue(), "application/pdf")},
            data={"metadata": json.dumps({"source": "start_fail"})},
            headers=headers,
        )
        assert retry.status_code == 200
