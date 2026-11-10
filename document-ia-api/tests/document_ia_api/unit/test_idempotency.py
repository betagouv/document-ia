import io
import asyncio
from unittest.mock import AsyncMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import UploadFile

from document_ia_api.core.idempotency.exceptions import (
    IdempotencyConflictException,
    IdempotencyInProgressException,
    IdempotencyReservationLostException,
    InvalidIdempotencyKeyException,
)
from document_ia_api.core.idempotency.key_validator import validate_idempotency_key
from document_ia_api.core.idempotency.models import (
    IdempotencyEntry,
    IdempotencyStatus,
)
from document_ia_api.core.idempotency.request_fingerprint import (
    compute_request_fingerprint,
)
from document_ia_api.infra.idempotency_service import (
    IdempotencyReservation,
    IdempotencyService,
    build_idempotency_redis_key,
    mark_completed_or_retain,
)


@pytest.fixture
async def real_redis():
    """A real Redis connection: these assertions are about stored state."""
    from redis.asyncio import Redis

    from document_ia_infra.redis.redis_settings import redis_settings

    client = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        db=redis_settings.REDIS_DB,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()


class TestIdempotencyKeyValidator:
    def test_key_none_is_valid(self):
        # Optional header: None passes without error
        validate_idempotency_key(None)

    def test_key_valid_strings(self):
        validate_idempotency_key("req-12345")
        validate_idempotency_key(str(uuid4()))
        validate_idempotency_key("a" * 256)
        validate_idempotency_key("Valid Key with Spaces 123!@#$%^&*()-_=+")

    def test_key_empty_string_raises_400(self):
        with pytest.raises(InvalidIdempotencyKeyException) as exc_info:
            validate_idempotency_key("")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "invalid_idempotency_key"

    def test_key_too_long_raises_400(self):
        with pytest.raises(InvalidIdempotencyKeyException) as exc_info:
            validate_idempotency_key("a" * 257)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "invalid_idempotency_key"

    def test_key_non_ascii_raises_400(self):
        with pytest.raises(InvalidIdempotencyKeyException) as exc_info:
            validate_idempotency_key("clé-idempotente-123")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "invalid_idempotency_key"

        with pytest.raises(InvalidIdempotencyKeyException) as exc_info:
            validate_idempotency_key("key-€-sign")
        assert exc_info.value.status_code == 400

    def test_key_control_characters_raise_400(self):
        for bad_char in ["\n", "\t", "\r", "\x00", "\x1f", "\x7f"]:
            with pytest.raises(InvalidIdempotencyKeyException) as exc_info:
                validate_idempotency_key(f"key{bad_char}123")
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail["error"] == "invalid_idempotency_key"


class TestRequestFingerprint:
    @pytest.mark.asyncio
    async def test_fingerprint_file_streaming_and_seek_reset(self):
        content = b"PDF-1.4 dummy document content that is readable in chunks"
        file_obj = io.BytesIO(content)
        upload_file = UploadFile(file=file_obj, filename="test.pdf")

        # Initial tell is 0
        assert upload_file.file.tell() == 0

        fp = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/doc-extr/execute",
            file=upload_file,
            params={"override": None, "metadata": '{"source": "test"}'},
        )

        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest

        # CRITICAL TEST: file cursor must be reset to 0
        assert upload_file.file.tell() == 0
        re_read = await upload_file.read()
        assert re_read == content

    @pytest.mark.asyncio
    async def test_fingerprint_determinism_param_ordering(self):
        file_content = b"document data"

        f1 = UploadFile(file=io.BytesIO(file_content), filename="doc.pdf")
        fp1 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file=f1,
            params={"override": '{"b": 2, "a": 1}', "metadata": '{"x": "y", "m": "n"}'},
        )

        f2 = UploadFile(file=io.BytesIO(file_content), filename="doc.pdf")
        fp2 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file=f2,
            params={"override": '{"a": 1, "b": 2}', "metadata": '{"m": "n", "x": "y"}'},
        )

        assert fp1 == fp2

    @pytest.mark.asyncio
    async def test_fingerprint_differs_on_different_files(self):
        f1 = UploadFile(file=io.BytesIO(b"file content A"), filename="doc.pdf")
        f2 = UploadFile(file=io.BytesIO(b"file content B"), filename="doc.pdf")

        fp1 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file=f1,
        )
        fp2 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file=f2,
        )

        assert fp1 != fp2

    @pytest.mark.asyncio
    async def test_fingerprint_differs_on_different_file_urls(self):
        fp1 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file_url="https://example.com/doc1.pdf",
        )
        fp2 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/extract/execute",
            file_url="https://example.com/doc2.pdf",
        )

        assert fp1 != fp2

    @pytest.mark.asyncio
    async def test_fingerprint_differs_on_different_routes(self):
        f1 = UploadFile(file=io.BytesIO(b"content"), filename="doc.pdf")
        f2 = UploadFile(file=io.BytesIO(b"content"), filename="doc.pdf")

        fp1 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf-1/execute",
            file=f1,
        )
        fp2 = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf-2/execute",
            file=f2,
        )

        assert fp1 != fp2

    @pytest.mark.asyncio
    async def test_fingerprint_preserves_json_value_types(self):
        """Different JSON types must not collapse into the same fingerprint.

        A string holding a JSON document and the equivalent object are distinct
        payloads, since metadata parsing keeps their types.
        """
        string_form = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": '{"source":"{}"}', "override": None},
        )
        object_form = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": '{"source":{}}', "override": None},
        )

        assert string_form != object_form

    @pytest.mark.asyncio
    async def test_fingerprint_keeps_nested_null_values(self):
        """A nested null is part of the payload and must not be dropped."""
        with_null = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": '{"source":null}', "override": None},
        )
        empty_object = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": "{}", "override": None},
        )

        assert with_null != empty_object

    @pytest.mark.asyncio
    async def test_fingerprint_still_ignores_formatting(self):
        """Key order and whitespace stay irrelevant to the fingerprint."""
        formatted = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={
                "metadata": '{ "b": 2, "a": 1 }',
                "override": '{"step": [{"param": "p", "value": 1}]}',
            },
        )
        compact = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={
                "metadata": '{"a":1,"b":2}',
                "override": '{"step":[{"value":1,"param":"p"}]}',
            },
        )

        assert formatted == compact

    @pytest.mark.asyncio
    async def test_fingerprint_keeps_invalid_json_verbatim(self):
        """Unparseable form fields still fingerprint deterministically."""
        first = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": "{not json", "override": None},
        )
        second = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": "{not json", "override": None},
        )
        other = await compute_request_fingerprint(
            method="POST",
            path="/api/v2/workflows/wf/execute",
            file_url="https://example.com/doc.pdf",
            params={"metadata": "{different", "override": None},
        )

        assert first == second
        assert first != other


class TestIdempotencyServiceUnit:
    def test_build_idempotency_redis_key(self):
        org_id = uuid4()
        key = build_idempotency_redis_key(
            version=2,
            organization_id=org_id,
            workflow_id="document-extraction-v2",
            idempotency_key="my-key-123",
        )
        assert key == f"idempotency:v2:{org_id}:document-extraction-v2:my-key-123"

    @pytest.mark.asyncio
    async def test_acquire_or_check_miss(self):
        mock_redis = AsyncMock()
        mock_redis.eval.return_value = None  # Lua returns nil on miss

        service = IdempotencyService(redis_client=mock_redis)
        exec_id = str(uuid4())
        result = await service.acquire_or_check(
            key="test-key",
            fingerprint="hash123",
            execution_id=exec_id,
        )

        assert result.is_replay is False
        assert result.execution_id == exec_id
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_or_check_hit_completed(self):
        mock_redis = AsyncMock()
        existing_exec_id = str(uuid4())
        existing_entry = IdempotencyEntry(
            fingerprint="hash123",
            execution_id=existing_exec_id,
            status=IdempotencyStatus.COMPLETED,
            created_at="2026-11-09T10:00:00Z",
        )
        mock_redis.eval.return_value = existing_entry.model_dump_json()

        service = IdempotencyService(redis_client=mock_redis)
        new_exec_id = str(uuid4())
        result = await service.acquire_or_check(
            key="test-key",
            fingerprint="hash123",
            execution_id=new_exec_id,
        )

        assert result.is_replay is True
        assert result.execution_id == existing_exec_id

    @pytest.mark.asyncio
    async def test_acquire_or_check_hit_conflict(self):
        mock_redis = AsyncMock()
        existing_entry = IdempotencyEntry(
            fingerprint="hash_original",
            execution_id=str(uuid4()),
            status=IdempotencyStatus.COMPLETED,
            created_at="2026-11-09T10:00:00Z",
        )
        mock_redis.eval.return_value = existing_entry.model_dump_json()

        service = IdempotencyService(redis_client=mock_redis)
        with pytest.raises(IdempotencyConflictException) as exc_info:
            await service.acquire_or_check(
                key="test-key",
                fingerprint="hash_different",
                execution_id=str(uuid4()),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "idempotency_conflict"

    @pytest.mark.asyncio
    async def test_acquire_or_check_hit_in_progress(self):
        mock_redis = AsyncMock()
        existing_exec_id = str(uuid4())
        existing_entry = IdempotencyEntry(
            fingerprint="hash123",
            execution_id=existing_exec_id,
            status=IdempotencyStatus.IN_PROGRESS,
            created_at="2026-11-09T10:00:00Z",
        )
        mock_redis.eval.return_value = existing_entry.model_dump_json()

        service = IdempotencyService(redis_client=mock_redis)
        with pytest.raises(IdempotencyInProgressException) as exc_info:
            await service.acquire_or_check(
                key="test-key",
                fingerprint="hash123",
                execution_id=str(uuid4()),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "idempotency_in_progress"
        assert exc_info.value.detail["execution_id"] == existing_exec_id

    @pytest.mark.asyncio
    async def test_mark_completed(self):
        mock_redis = AsyncMock()
        mock_redis.eval.return_value = 1

        service = IdempotencyService(redis_client=mock_redis)
        ok = await service.mark_completed(
            key="test-key",
            execution_id="exec-123",
        )
        assert ok is True
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_key(self):
        mock_redis = AsyncMock()
        mock_redis.eval.return_value = 1

        service = IdempotencyService(redis_client=mock_redis)
        ok = await service.release_key(
            key="test-key",
            execution_id="exec-123",
        )
        assert ok is True
        mock_redis.eval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renew_extends_only_owned_in_progress_entry(self):
        mock_redis = AsyncMock()
        mock_redis.eval.return_value = 1

        service = IdempotencyService(redis_client=mock_redis)
        renewed = await service.renew(key="test-key", execution_id="exec-123")

        assert renewed is True
        # The TTL is applied by the Lua script only for an owned IN_PROGRESS entry.
        assert "IN_PROGRESS" in mock_redis.eval.await_args.args[0]

    @pytest.mark.asyncio
    async def test_renew_reports_ownership_loss(self):
        mock_redis = AsyncMock()
        mock_redis.eval.return_value = 0

        service = IdempotencyService(redis_client=mock_redis)
        assert await service.renew(key="test-key", execution_id="exec-123") is False




class TestIdempotencyReservation:
    @pytest.mark.asyncio
    async def test_renewal_keeps_the_lease_alive_during_admission(self):
        """A slow admission must keep renewing instead of letting the key lapse."""
        service = AsyncMock(spec=IdempotencyService)
        service.renew.return_value = True

        reservation = IdempotencyReservation(
            service,
            key="k",
            execution_id="e",
            lock_ttl_seconds=0.03,
            renewal_interval_seconds=0.01,
        )

        async with reservation:
            await asyncio.sleep(0.05)

        assert reservation.is_lost is False
        assert service.renew.await_count >= 2

    @pytest.mark.asyncio
    async def test_renewal_failure_marks_the_reservation_lost(self):
        """Losing renewal must mark the reservation lost, so publish refuses."""
        service = AsyncMock(spec=IdempotencyService)
        service.renew.return_value = False

        async with IdempotencyReservation(
            service,
            key="k",
            execution_id="e",
            renewal_interval_seconds=0.01,
        ) as reservation:
            await asyncio.sleep(0.05)
            publisher = AsyncMock()
            with pytest.raises(IdempotencyReservationLostException):
                await reservation.publish(publisher, "m")

        assert reservation.is_lost is True
        publisher.publish_message_fenced.assert_not_awaited()


class TestPostAcceptanceTracking:
    """Completion is one atomic write: complete, or recreate the mapping.

    The previous design completed first and fell back to extending the TTL. That
    left two holes, both now covered here: if both writes failed the key lapsed
    and a retry scheduled the execution twice, and if only completion failed the
    entry stayed IN_PROGRESS for the whole retention, answering every retry with
    409 instead of replaying it.
    """

    @pytest.mark.asyncio
    async def test_accepted_execution_is_recorded(self):
        service = AsyncMock(spec=IdempotencyService)
        service.complete_or_retain.return_value = True

        await mark_completed_or_retain(
            service, key="k", execution_id="e", fingerprint="fp", created_at="t"
        )

        service.complete_or_retain.assert_awaited_once()
        kwargs = service.complete_or_retain.await_args.kwargs
        assert kwargs["fingerprint"] == "fp"
        assert kwargs["created_at"] == "t"

    @pytest.mark.asyncio
    async def test_unreachable_redis_does_not_raise(self):
        """Tracking must never turn an accepted execution into an error."""
        service = AsyncMock(spec=IdempotencyService)
        service.complete_or_retain.side_effect = RuntimeError("redis down")

        await mark_completed_or_retain(
            service, key="k", execution_id="e", fingerprint="fp", created_at="t"
        )

    @pytest.mark.asyncio
    async def test_key_taken_by_another_request_is_logged_not_raised(self):
        service = AsyncMock(spec=IdempotencyService)
        service.complete_or_retain.return_value = False

        await mark_completed_or_retain(
            service, key="k", execution_id="e", fingerprint="fp", created_at="t"
        )

        service.complete_or_retain.assert_awaited_once()


class TestMarkCompletedConnectionFailures:
    @pytest.mark.asyncio
    async def test_connection_failure_returns_false_instead_of_raising(self):
        """A Redis outage must not escape mark_completed's contract."""
        service = IdempotencyService(redis_client=None)

        with patch.object(
            service,
            "_get_connection",
            new=AsyncMock(side_effect=RuntimeError("redis unreachable")),
        ):
            assert await service.mark_completed(key="k", execution_id="e") is False


class TestAtomicCompletion:
    """Completion must be one write, never "complete then maybe extend".

    Both holes found in review are pinned here against real Redis.
    """

    @pytest.mark.asyncio
    async def test_lapsed_reservation_is_recreated_as_completed(self, real_redis):
        service = IdempotencyService(redis_client=real_redis)
        key = f"idem-atomic-{uuid4()}"
        recorded = await service.complete_or_retain(
            key=key,
            execution_id="exec-A",
            fingerprint="fp",
            created_at="2026-11-10T00:00:00Z",
        )
        assert recorded is True

        stored = IdempotencyEntry.model_validate_json(await real_redis.get(key))
        assert stored.status == IdempotencyStatus.COMPLETED
        assert stored.execution_id == "exec-A"
        # Retained for the completion TTL, not the short lock TTL.
        assert await real_redis.ttl(key) > 3600

        # A retry replays the accepted execution instead of scheduling it again.
        result = await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-B"
        )
        assert result.is_replay is True
        assert result.execution_id == "exec-A"
        await real_redis.delete(key)

    @pytest.mark.asyncio
    async def test_in_progress_entry_is_completed_not_left_blocking(self, real_redis):
        service = IdempotencyService(redis_client=real_redis)
        key = f"idem-inprog-{uuid4()}"
        await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-A", lock_ttl_seconds=60
        )

        recorded = await service.complete_or_retain(
            key=key,
            execution_id="exec-A",
            fingerprint="fp",
            created_at="2026-11-10T00:00:00Z",
        )
        assert recorded is True

        stored = IdempotencyEntry.model_validate_json(await real_redis.get(key))
        assert stored.status == IdempotencyStatus.COMPLETED

        result = await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-B"
        )
        assert result.is_replay is True
        await real_redis.delete(key)

    @pytest.mark.asyncio
    async def test_does_not_clobber_a_key_owned_by_another_request(self, real_redis):
        service = IdempotencyService(redis_client=real_redis)
        key = f"idem-owned-{uuid4()}"
        await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-B", lock_ttl_seconds=60
        )

        recorded = await service.complete_or_retain(
            key=key,
            execution_id="exec-A",
            fingerprint="fp",
            created_at="2026-11-10T00:00:00Z",
        )

        assert recorded is False
        stored = IdempotencyEntry.model_validate_json(await real_redis.get(key))
        assert stored.execution_id == "exec-B"
        await real_redis.delete(key)


class TestFencedPublicationContract:
    @pytest.mark.asyncio
    async def test_reservation_publishes_through_the_fence(self):
        """Production must never publish outside the ownership fence."""
        service = AsyncMock(spec=IdempotencyService)
        publisher = AsyncMock()
        publisher.publish_message_fenced.return_value = "1-0"
        reservation = IdempotencyReservation(
            service, key="k", execution_id="exec-A", lock_ttl_seconds=60
        )

        await reservation.publish(publisher, "message")

        publisher.publish_message_fenced.assert_awaited_once()
        # A separate, unfenced publication would reopen the race.
        publisher.publish_message.assert_not_awaited()
        kwargs = publisher.publish_message_fenced.await_args.kwargs
        assert kwargs["reservation_key"] == "k"
        assert kwargs["reservation_execution_id"] == "exec-A"

    @pytest.mark.asyncio
    async def test_lost_fence_raises_and_marks_lost(self):
        from document_ia_infra.redis.publisher import ReservationLostError

        service = AsyncMock(spec=IdempotencyService)
        publisher = AsyncMock()
        publisher.publish_message_fenced.side_effect = ReservationLostError()
        reservation = IdempotencyReservation(
            service, key="k", execution_id="exec-A", lock_ttl_seconds=60
        )

        with pytest.raises(IdempotencyReservationLostException) as exc_info:
            await reservation.publish(publisher, "message")

        assert exc_info.value.status_code == 503
        assert reservation.is_lost is True

    @pytest.mark.asyncio
    async def test_publish_after_loss_never_reaches_redis(self):
        from document_ia_infra.redis.publisher import ReservationLostError

        service = AsyncMock(spec=IdempotencyService)
        publisher = AsyncMock()
        publisher.publish_message_fenced.side_effect = ReservationLostError()
        reservation = IdempotencyReservation(
            service, key="k", execution_id="exec-A", lock_ttl_seconds=60
        )
        with pytest.raises(IdempotencyReservationLostException):
            await reservation.publish(publisher, "m")

        with pytest.raises(IdempotencyReservationLostException):
            await reservation.publish(publisher, "m")
        assert publisher.publish_message_fenced.await_count == 1


class TestReleaseNeverDeletesAcceptedMapping:
    """Route cleanup must not undo an accepted execution.

    The route releases the key on any failure. If the publication actually
    succeeded but its reply was lost, the mapping records an accepted execution
    and deleting it lets the next retry schedule the work a second time.
    """

    @pytest.mark.asyncio
    async def test_completed_mapping_survives_release(self, real_redis):
        service = IdempotencyService(redis_client=real_redis)
        key = f"idem-release-completed-{uuid4()}"
        await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-A", lock_ttl_seconds=60
        )
        await service.complete_or_retain(
            key=key,
            execution_id="exec-A",
            fingerprint="fp",
            created_at="2026-11-10T00:00:00Z",
        )

        released = await service.release_key(key=key, execution_id="exec-A")

        assert released is False
        stored = IdempotencyEntry.model_validate_json(await real_redis.get(key))
        assert stored.status == IdempotencyStatus.COMPLETED
        # And the retry still replays rather than scheduling again.
        result = await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-B"
        )
        assert result.is_replay is True
        await real_redis.delete(key)

    @pytest.mark.asyncio
    async def test_in_progress_reservation_is_still_released(self, real_redis):
        service = IdempotencyService(redis_client=real_redis)
        key = f"idem-release-inprog-{uuid4()}"
        await service.acquire_or_check(
            key=key, fingerprint="fp", execution_id="exec-A", lock_ttl_seconds=60
        )

        released = await service.release_key(key=key, execution_id="exec-A")

        assert released is True
        assert await real_redis.get(key) is None


class TestPublicationTimeout:
    @pytest.mark.asyncio
    async def test_fenced_publish_is_bounded_and_reports_unknown(self):
        """A stalled Redis must neither hang the request nor look like a rejection."""
        import asyncio

        from document_ia_infra.redis.model.workflow_execution_message import (
            WorkflowExecutionMessage,
        )
        from document_ia_infra.redis.publisher import (
            PublicationOutcomeUnknownError,
            Publisher,
        )
        from document_ia_infra.redis.redis_settings import redis_settings

        connection = AsyncMock()

        async def never(*args, **kwargs):
            await asyncio.sleep(30)

        connection.eval.side_effect = never
        manager = AsyncMock()
        manager.get_connection.return_value = connection
        publisher = Publisher("event_stream", current_redis_manager=manager)

        loop = asyncio.get_running_loop()
        started = loop.time()
        with patch.object(redis_settings, "PUBLISH_TIMEOUT_SECONDS", 0.2):
            with pytest.raises(PublicationOutcomeUnknownError):
                await publisher.publish_message_fenced(
                    WorkflowExecutionMessage(workflow_execution_id="exec-A"),
                    reservation_key="k",
                    reservation_execution_id="exec-A",
                    reservation_ttl_seconds=60,
                )
        elapsed = loop.time() - started

        assert elapsed < 5, f"fenced publication was not bounded: {elapsed:.2f}s"


class TestRejectionVersusUnknownOutcome:
    """A Redis error reply is a confirmed rejection, not an ambiguous outcome.

    Treating a rejection as unknown makes the caller mark a never-published
    execution as accepted, so the client gets success for work that was not
    queued and every retry replays it for the whole retention period.
    """

    @staticmethod
    async def _attempt(error):
        from document_ia_infra.redis.model.workflow_execution_message import (
            WorkflowExecutionMessage,
        )
        from document_ia_infra.redis.publisher import Publisher

        connection = AsyncMock()
        connection.eval.side_effect = error
        manager = AsyncMock()
        manager.get_connection.return_value = connection
        publisher = Publisher("event_stream", current_redis_manager=manager)
        return publisher, WorkflowExecutionMessage(workflow_execution_id="exec-A")

    @pytest.mark.asyncio
    async def test_redis_error_reply_is_a_rejection(self):
        from redis.exceptions import ResponseError

        from document_ia_infra.redis.publisher import (
            PublicationOutcomeUnknownError,
            PublishFailedError,
        )

        publisher, message = await self._attempt(ResponseError("OOM command not allowed"))
        with pytest.raises(PublishFailedError) as exc_info:
            await publisher.publish_message_fenced(
                message,
                reservation_key="k",
                reservation_execution_id="exec-A",
                reservation_ttl_seconds=60,
            )

        assert not isinstance(exc_info.value, PublicationOutcomeUnknownError)

    @pytest.mark.asyncio
    async def test_transport_failure_is_unknown(self):
        from redis.exceptions import ConnectionError as RedisConnectionError

        from document_ia_infra.redis.publisher import (
            PublicationOutcomeUnknownError,
        )

        publisher, message = await self._attempt(
            RedisConnectionError("connection reset by peer")
        )
        with pytest.raises(PublicationOutcomeUnknownError):
            await publisher.publish_message_fenced(
                message,
                reservation_key="k",
                reservation_execution_id="exec-A",
                reservation_ttl_seconds=60,
            )
