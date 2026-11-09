import io
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from document_ia_api.core.idempotency.exceptions import (
    IdempotencyConflictException,
    IdempotencyInProgressException,
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
    IdempotencyService,
    build_idempotency_redis_key,
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
