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

    @pytest.mark.asyncio
    async def test_is_reservation_owned(self):
        mock_redis = AsyncMock()
        service = IdempotencyService(redis_client=mock_redis)

        mock_redis.eval.return_value = 1
        assert (
            await service.is_reservation_owned(key="k", execution_id="e") is True
        )

        mock_redis.eval.return_value = 0
        assert (
            await service.is_reservation_owned(key="k", execution_id="e") is False
        )

    @pytest.mark.asyncio
    async def test_is_reservation_owned_treats_redis_failure_as_not_owned(self):
        mock_redis = AsyncMock()
        mock_redis.eval.side_effect = RuntimeError("redis down")

        service = IdempotencyService(redis_client=mock_redis)
        assert (
            await service.is_reservation_owned(key="k", execution_id="e") is False
        )


class TestIdempotencyReservation:
    @pytest.mark.asyncio
    async def test_renewal_keeps_lease_alive_past_lock_ttl(self):
        """A slow admission must keep renewing instead of letting the key lapse."""
        service = AsyncMock(spec=IdempotencyService)
        service.renew.return_value = True
        service.is_reservation_owned.return_value = True

        reservation = IdempotencyReservation(
            service,
            key="k",
            execution_id="e",
            lock_ttl_seconds=60,
            renewal_interval_seconds=0.01,
        )

        async with reservation:
            await asyncio.sleep(0.05)
            await reservation.ensure_owned()

        assert reservation.is_lost is False
        assert service.renew.await_count >= 2

    @pytest.mark.asyncio
    async def test_renewal_failure_marks_reservation_lost(self):
        service = AsyncMock(spec=IdempotencyService)
        service.renew.return_value = False

        reservation = IdempotencyReservation(
            service,
            key="k",
            execution_id="e",
            renewal_interval_seconds=0.01,
        )

        async with reservation:
            await asyncio.sleep(0.05)
            with pytest.raises(IdempotencyReservationLostException):
                await reservation.ensure_owned()

        assert reservation.is_lost is True

    @pytest.mark.asyncio
    async def test_ensure_owned_blocks_publication_after_reacquisition(self):
        """A key re-acquired by another request must stop this publication."""
        service = AsyncMock(spec=IdempotencyService)
        service.renew.return_value = True
        service.is_reservation_owned.return_value = False

        reservation = IdempotencyReservation(
            service,
            key="k",
            execution_id="e",
            renewal_interval_seconds=60,
        )

        async with reservation:
            with pytest.raises(IdempotencyReservationLostException) as exc_info:
                await reservation.ensure_owned()

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error"] == "idempotency_reservation_lost"


class TestPostAcceptanceTracking:
    @pytest.mark.asyncio
    async def test_completed_key_needs_no_fallback(self):
        service = AsyncMock(spec=IdempotencyService)
        service.mark_completed.return_value = True

        await mark_completed_or_retain(service, key="k", execution_id="e")

        service.mark_completed.assert_awaited_once()
        service.renew.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tracking_failure_retains_accepted_execution(self):
        """A failed completion must extend retention, not surface an error."""
        service = AsyncMock(spec=IdempotencyService)
        service.mark_completed.return_value = False
        service.renew.return_value = True

        await mark_completed_or_retain(service, key="k", execution_id="e")

        service.renew.assert_awaited_once()
        assert service.renew.await_args.kwargs["lock_ttl_seconds"] > 3600

    @pytest.mark.asyncio
    async def test_unreachable_redis_does_not_raise(self):
        """Tracking must never turn an accepted execution into an error."""
        service = AsyncMock(spec=IdempotencyService)
        service.mark_completed.side_effect = RuntimeError("redis down")
        service.renew.side_effect = RuntimeError("redis down")

        # The route relies on this never raising after an execution is accepted.
        await mark_completed_or_retain(service, key="k", execution_id="e")


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
