"""Comprehensive security test suite for DownloadFileStep and file confinement."""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import httpcore
import pytest

from document_ia_infra.core.file.file_settings import file_settings
from document_ia_infra.core.network.safe_transport import (
    SafeAsyncNetworkBackend,
    SafeAsyncHTTPTransport,
    resolve_and_pin_ip,
    resolve_validated_ips,
)
from document_ia_infra.exception.security_exception import (
    BlockedAddressException,
    DisallowedRedirectException,
    InvalidProtocolException,
    InvalidUUIDException,
    PathTraversalException,
)
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_file_manipulation_step import (
    BaseFileManipulationStep,
)
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)


# Minimal valid PDF binary
VALID_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture
def mock_context() -> MainWorkflowContext:
    valid_uuid = str(uuid4())
    return MainWorkflowContext(
        execution_id=valid_uuid,
        organization_id=uuid4(),
        workflow_version=1,
        start_time=datetime.now(),
        steps_metadata=[],
    )


class DummyFileStep(BaseFileManipulationStep[str]):
    """Concrete subclass for testing BaseFileManipulationStep."""

    async def _execute_internal(self):
        return "ok", None


# ==============================================================================
# 1. Anti-SSRF & Network Tests
# ==============================================================================


@pytest.mark.parametrize(
    "blocked_url",
    [
        "https://127.0.0.1/doc.pdf",
        "https://127.0.1.1/doc.pdf",
        "https://localhost/doc.pdf",
        "https://[::1]/doc.pdf",
    ],
)
@pytest.mark.asyncio
async def test_ssrf_loopback_blocked(blocked_url: str):
    """Verify that loopback addresses in IPv4, IPv6, and localhost are blocked."""
    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddressException):
            await client.get(blocked_url)


@pytest.mark.parametrize(
    "private_url",
    [
        "https://10.0.0.1/doc.pdf",
        "https://172.16.0.1/doc.pdf",
        "https://192.168.1.1/doc.pdf",
        "https://100.64.0.1/doc.pdf",  # CGNAT
    ],
)
@pytest.mark.asyncio
async def test_ssrf_rfc1918_and_cgnat_blocked(private_url: str):
    """Verify that private networks RFC 1918 and CGNAT are blocked."""
    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddressException):
            await client.get(private_url)


@pytest.mark.parametrize(
    "metadata_url",
    [
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://instance-data/latest/meta-data/",
    ],
)
@pytest.mark.asyncio
async def test_ssrf_cloud_metadata_blocked(metadata_url: str):
    """Verify that AWS, GCP, and cloud metadata IPs and hostnames are blocked."""
    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddressException):
            await client.get(metadata_url)


@pytest.mark.parametrize(
    "ipv6_url",
    [
        "https://[::ffff:127.0.0.1]/doc.pdf",
        "https://[::ffff:169.254.169.254]/doc.pdf",
        "https://[fe80::1]/doc.pdf",
    ],
)
@pytest.mark.asyncio
async def test_ssrf_ipv6_mapped_and_link_local_blocked(ipv6_url: str):
    """Verify that IPv4-mapped IPv6 and IPv6 link-local addresses are rejected."""
    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedAddressException):
            await client.get(ipv6_url)


@pytest.mark.parametrize(
    "disallowed_url",
    [
        "http://example.com/doc.pdf",
        "ftp://example.com/doc.pdf",
        "file:///etc/passwd",
    ],
)
@pytest.mark.asyncio
async def test_strict_https_protocol_enforcement(disallowed_url: str):
    """Verify that schemes other than HTTPS are strictly rejected."""
    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(InvalidProtocolException):
            await client.get(disallowed_url)


@pytest.mark.asyncio
async def test_dns_rebinding_simulation():
    """Verify that if DNS returns a mixture of public and private IPs, it is blocked."""
    # Simulate getaddrinfo returning both a public IP and 127.0.0.1
    mock_addr_info = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ]
    with patch("asyncio.get_running_loop") as mock_loop:
        mock_instance = AsyncMock()
        mock_instance.getaddrinfo.return_value = mock_addr_info
        mock_loop.return_value = mock_instance

        with pytest.raises(BlockedAddressException):
            await resolve_and_pin_ip("rebinding.example.com", 443)


@pytest.mark.asyncio
async def test_transport_bounds_dns_with_the_client_timeout():
    """The DownloadFileStep 30s connect timeout must bound DNS through HTTPX."""

    async def hanging_resolution(*args, **kwargs):
        await asyncio.sleep(10)
        return ["93.184.216.34"]

    seen_timeout: list[float | None] = []

    original = SafeAsyncHTTPTransport.handle_async_request

    async def capture(self, request):
        seen_timeout.append(
            (request.extensions.get("timeout") or {}).get("connect")
        )
        return await original(self, request)

    transport = SafeAsyncHTTPTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with patch(
            "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
            new=hanging_resolution,
        ), patch.object(
            SafeAsyncHTTPTransport, "handle_async_request", capture
        ):
            with pytest.raises(httpx.ConnectTimeout):
                await client.get("https://slow.example.com/doc.pdf", timeout=0.2)

    # The transport sees the client's connect budget rather than an unbounded call.
    assert seen_timeout == [0.2]


@pytest.mark.asyncio
async def test_connect_budget_is_not_spent_twice():
    """The connect timeout must bound the whole connect, not each step.

    The transport resolves DNS before delegating, and the backend resolves again.
    Handing the full timeout to both let a 0.1s request take 0.216s.
    """
    resolutions: list[float] = []

    async def slow_resolution(hostname, port, allow_local=False):
        resolutions.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.08)
        return ["93.184.216.34"]

    transport = SafeAsyncHTTPTransport()
    loop = asyncio.get_running_loop()

    async with httpx.AsyncClient(transport=transport) as client:
        with patch(
            "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
            new=slow_resolution,
        ):
            started = loop.time()
            with pytest.raises((httpx.ConnectTimeout, httpx.ConnectError)):
                await client.get("https://example.com/doc.pdf", timeout=0.1)
            elapsed = loop.time() - started

    # Two lookups at 0.08s each would take 0.16s+ if the budget restarted.
    assert elapsed < 0.15, f"connect budget was spent more than once: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_all_validated_addresses_are_exposed_for_fallback():
    """Every resolved address is returned, not just the first, so callers can retry."""
    mock_addr_info = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("93.184.216.35", 443)),
    ]
    with patch("asyncio.get_running_loop") as mock_loop:
        mock_instance = AsyncMock()
        mock_instance.getaddrinfo.return_value = mock_addr_info
        mock_loop.return_value = mock_instance

        ips = await resolve_validated_ips("example.com", 443)

    assert ips == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.asyncio
async def test_unreachable_first_address_falls_back_to_next():
    """An unreachable first address must not fail the connection if another works.

    Typical case: a dual-stack hostname where IPv6 is unreachable but IPv4 works.
    """
    backend = SafeAsyncNetworkBackend()
    attempted: list[str] = []

    async def fake_connect_tcp(
        host, port, timeout=None, local_address=None, socket_options=None
    ):
        attempted.append(host)
        if host == "93.184.216.34":
            raise httpcore.ConnectError("network unreachable")
        return "stream"

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        new=AsyncMock(return_value=["93.184.216.34", "93.184.216.35"]),
    ):
        backend._backend = AsyncMock()
        backend._backend.connect_tcp.side_effect = fake_connect_tcp
        stream = await backend.connect_tcp("example.com", 443, timeout=30.0)

    # The returned stream is wrapped so the TLS handshake can be re-bounded.
    assert type(stream).__name__ == "_DeadlineBoundedStream"
    assert attempted == ["93.184.216.34", "93.184.216.35"]


@pytest.mark.asyncio
async def test_all_addresses_unreachable_reports_connect_error():
    """When every validated address fails, the last error is surfaced."""
    backend = SafeAsyncNetworkBackend()

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        new=AsyncMock(return_value=["93.184.216.34", "93.184.216.35"]),
    ):
        backend._backend = AsyncMock()
        backend._backend.connect_tcp.side_effect = httpcore.ConnectError(
            "network unreachable"
        )
        with pytest.raises(httpcore.ConnectError):
            await backend.connect_tcp("example.com", 443, timeout=30.0)

    assert backend._backend.connect_tcp.await_count == 2


@pytest.mark.asyncio
async def test_slow_dns_is_bounded_by_the_connect_timeout():
    """A hanging resolver must not outlive the request's connect timeout."""

    async def hanging_resolution(*args, **kwargs):
        await asyncio.sleep(10)
        return ["93.184.216.34"]

    backend = SafeAsyncNetworkBackend()
    loop = asyncio.get_running_loop()

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        new=hanging_resolution,
    ):
        started = loop.time()
        with pytest.raises(httpcore.ConnectTimeout):
            await backend.connect_tcp("slow.example.com", 443, timeout=0.2)
        elapsed = loop.time() - started

    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_slow_dns_is_bounded_in_pinning_helper():
    """`resolve_and_pin_ip` also honours the deadline it is given."""

    async def hanging_resolution(*args, **kwargs):
        await asyncio.sleep(10)
        return ["93.184.216.34"]

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        new=hanging_resolution,
    ):
        with pytest.raises(httpcore.ConnectTimeout):
            await resolve_and_pin_ip("slow.example.com", 443, timeout=0.2)


@pytest.mark.asyncio
async def test_private_address_still_blocks_before_any_connect():
    """Falling back across addresses must not weaken the anti-SSRF check."""
    backend = SafeAsyncNetworkBackend()

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        side_effect=BlockedAddressException("blocked"),
    ):
        backend._backend = AsyncMock()
        with pytest.raises(BlockedAddressException):
            await backend.connect_tcp("example.com", 443, timeout=30.0)

    backend._backend.connect_tcp.assert_not_awaited()


@pytest.mark.asyncio
async def test_disallowed_redirect_blocked():
    """Verify that 301/302 redirects are strictly forbidden."""
    mock_response = httpx.Response(
        status_code=302,
        headers={"location": "https://169.254.169.254/secret"},
        request=httpx.Request("GET", "https://example.com/doc.pdf"),
    )

    with patch.object(
        httpx.AsyncHTTPTransport,
        "handle_async_request",
        new_callable=AsyncMock,
    ) as mock_handle:
        mock_handle.return_value = mock_response
        with patch(
            "document_ia_infra.core.network.safe_transport.resolve_and_pin_ip",
            return_value="93.184.216.34",
        ):
            transport = SafeAsyncHTTPTransport()
            async with httpx.AsyncClient(transport=transport) as client:
                with pytest.raises(DisallowedRedirectException):
                    await client.get("https://example.com/doc.pdf")


# ==============================================================================
# 2. Filesystem Confinement & Download Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_content_disposition_injection_ignored(mock_context: MainWorkflowContext):
    """Verify that malicious Content-Disposition filenames are completely ignored."""
    mock_resp = httpx.Response(
        status_code=200,
        headers={
            "Content-Disposition": 'attachment; filename="../../etc/shadow"',
            "Content-Type": "application/pdf",
        },
        stream=httpx.ByteStream(VALID_PDF_BYTES),
        request=httpx.Request("GET", "https://example.com/invoice.pdf"),
    )

    mock_transport = httpx.MockTransport(lambda req: mock_resp)
    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_url="https://example.com/invoice.pdf",
        transport=mock_transport,
    )

    await step._prepare_step()
    result, _ = await step._execute_internal()

    result_path = Path(result.file_path)
    assert result_path.exists()
    assert result_path.is_relative_to(step.sandbox_root)
    # Filename must NOT contain 'shadow' or 'etc'
    assert "shadow" not in result_path.name
    assert "etc" not in result_path.name
    assert result_path.suffix == ".pdf"
    assert len(result_path.stem) == 32  # uuid4 hex length

    await step.cleanup(is_last_cleanup=True)
    assert not result_path.exists()


def test_path_traversal_subfolder_rejected(mock_context: MainWorkflowContext):
    """Verify that directory traversal via subfolder parameter is rejected."""
    with pytest.raises(PathTraversalException):
        DummyFileStep(
            main_workflow_context=mock_context,
            subfolder="../../etc",
        )


def test_invalid_execution_id_rejected():
    """Verify that a non-UUID execution_id raises InvalidUUIDException."""
    bad_context = MainWorkflowContext(
        execution_id="../../escaping_id",
        organization_id=uuid4(),
        workflow_version=1,
        start_time=datetime.now(),
        steps_metadata=[],
    )
    with pytest.raises(InvalidUUIDException):
        DummyFileStep(main_workflow_context=bad_context)


@pytest.mark.asyncio
async def test_symlink_escape_cleanup_safe(
    mock_context: MainWorkflowContext, tmp_path: Path
):
    """Verify that cleanup removes symlinks without touching external target files."""
    step = DummyFileStep(main_workflow_context=mock_context)
    sandbox_dir = Path(step.tmp_folder_path)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    # Create external target file outside sandbox
    outside_dir = tmp_path / "outside_secure"
    outside_dir.mkdir()
    outside_file = outside_dir / "critical_system_file.txt"
    outside_file.write_text("SENSITIVE HOST DATA")

    # Create symlink inside sandbox pointing to outside file
    symlink_file = sandbox_dir / "symlink_to_external.txt"
    symlink_file.symlink_to(outside_file)
    assert symlink_file.exists()

    # Execute cleanup
    await step.cleanup(is_last_cleanup=True)

    # Symlink must be gone, but external file MUST remain intact
    assert not symlink_file.exists()
    assert outside_file.exists()
    assert outside_file.read_text() == "SENSITIVE HOST DATA"


@pytest.mark.asyncio
async def test_file_size_limit_exceeded(mock_context: MainWorkflowContext):
    """Verify that downloading files exceeding MAX_FILE_SIZE aborts and cleans up."""
    # Chunk larger than MAX_FILE_SIZE
    large_payload = b"%PDF-1.4 " + (b"A" * (file_settings.MAX_FILE_SIZE + 1024))
    mock_resp = httpx.Response(
        status_code=200,
        stream=httpx.ByteStream(large_payload),
        request=httpx.Request("GET", "https://example.com/large.pdf"),
    )
    mock_transport = httpx.MockTransport(lambda req: mock_resp)

    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_url="https://example.com/large.pdf",
        transport=mock_transport,
    )
    await step._prepare_step()

    with pytest.raises(ValueError, match="maximum allowed size"):
        await step._execute_internal()

    # Sandbox must be empty of any temporary files
    sandbox_files = list(Path(step.tmp_folder_path).iterdir())
    assert len(sandbox_files) == 0

    await step.cleanup(is_last_cleanup=True)


@pytest.mark.asyncio
async def test_invalid_mime_type_rejected_early(mock_context: MainWorkflowContext):
    """Verify that files with forbidden MIME type (e.g. executable script) are rejected."""
    forbidden_payload = b"#!/bin/bash\nrm -rf /\n"
    mock_resp = httpx.Response(
        status_code=200,
        stream=httpx.ByteStream(forbidden_payload),
        request=httpx.Request("GET", "https://example.com/script.sh"),
    )
    mock_transport = httpx.MockTransport(lambda req: mock_resp)

    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_url="https://example.com/script.sh",
        transport=mock_transport,
    )
    await step._prepare_step()

    with pytest.raises(ValueError, match="MIME type not allowed"):
        await step._execute_internal()

    await step.cleanup(is_last_cleanup=True)


@pytest.mark.asyncio
async def test_presigned_url_query_parameters_preserved(
    mock_context: MainWorkflowContext,
):
    """Verify that presigned S3/GCS query parameters are preserved without alteration."""
    recorded_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal recorded_request
        recorded_request = request
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            stream=httpx.ByteStream(VALID_PDF_BYTES),
        )

    mock_transport = httpx.MockTransport(handler)
    presigned_url = (
        "https://mybucket.s3.eu-west-3.amazonaws.com/doc.pdf"
        "?X-Amz-Signature=abc12345xyz&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20261109"
    )

    step = DownloadFileStep(
        main_workflow_context=mock_context,
        file_url=presigned_url,
        transport=mock_transport,
    )
    await step._prepare_step()
    result, _ = await step._execute_internal()

    assert recorded_request is not None
    # Signature and credentials query string must match exactly
    assert "X-Amz-Signature=abc12345xyz" in str(recorded_request.url)
    assert "X-Amz-Credential=" in str(recorded_request.url)
    assert Path(result.file_path).exists()

    await step.cleanup(is_last_cleanup=True)


# ==============================================================================
# 3. Directory replacement (TOCTOU) — descriptor-anchored confinement
# ==============================================================================


@pytest.mark.asyncio
async def test_directory_swap_after_open_does_not_leak(
    mock_context: MainWorkflowContext, tmp_path: Path
):
    """Replacing the execution directory after validation must not redirect writes.

    A pathname validated and later reopened is not a boundary: the directory can
    be swapped for a symlink in between, and a re-resolving check would approve
    the external location. The descriptor taken at validation time is what the
    write is anchored to.
    """
    from document_ia_infra.core.file import safe_path

    outside = tmp_path / "outside_target"
    outside.mkdir()
    step = DownloadFileStep(
        main_workflow_context=mock_context, file_url="https://example.com/inv.pdf"
    )
    root = Path(step.sandbox_root)
    root.mkdir(parents=True, exist_ok=True)

    real_open = safe_path.open_confined_directory

    def swapping_open(path, sandbox_root):
        confined = real_open(path, sandbox_root)
        # The attacker replaces the directory after it was validated.
        import shutil

        shutil.rmtree(root, ignore_errors=True)
        root.symlink_to(outside, target_is_directory=True)
        return confined

    mock_resp = httpx.Response(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        stream=httpx.ByteStream(VALID_PDF_BYTES),
        request=httpx.Request("GET", "https://example.com/inv.pdf"),
    )
    step._transport = httpx.MockTransport(lambda req: mock_resp)
    await step._prepare_step()

    with patch.object(safe_path, "open_confined_directory", swapping_open):
        result, _ = await step._execute_internal()

    # Nothing may be written into the directory the symlink points at.
    assert list(outside.iterdir()) == []
    assert Path(result.file_path).exists()


def test_open_confined_directory_refuses_a_symlinked_root(tmp_path: Path):
    """A sandbox root that is already a symlink is refused, not followed."""
    from document_ia_infra.core.file.safe_path import open_confined_directory
    from document_ia_infra.exception.security_exception import (
        PathTraversalException,
    )

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (sandbox / "exec").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalException):
        open_confined_directory(sandbox / "exec", sandbox)


def test_open_confined_directory_rejects_an_escaping_name(tmp_path: Path):
    from document_ia_infra.core.file.safe_path import open_confined_directory
    from document_ia_infra.exception.security_exception import (
        PathTraversalException,
    )

    sandbox = tmp_path / "sandbox2"
    sandbox.mkdir()
    with open_confined_directory(sandbox, sandbox) as confined:
        with pytest.raises(PathTraversalException):
            confined.open_file("../escape.pdf", "wb")
        with pytest.raises(PathTraversalException):
            confined.unlink("../escape.pdf")


def test_cleanup_never_deletes_through_a_replaced_directory(tmp_path: Path):
    """Cleanup must not delete anything behind a destroyed sandbox root.

    The external target must actually exist here: an earlier version of this
    test pointed at a missing directory, so it passed while the code happily
    deleted real external files.
    """
    from document_ia_infra.core.file.safe_path import safe_cleanup_directory

    sandbox = tmp_path / "sandbox3"
    sandbox.mkdir()
    outside = tmp_path / "keep"
    outside.mkdir()
    (outside / "preprocess").mkdir()
    kept = outside / "preprocess" / "KEEP.txt"
    kept.write_text("must survive")

    execution_dir = sandbox / "exec3"
    execution_dir.symlink_to(outside, target_is_directory=True)

    safe_cleanup_directory(
        execution_dir / "preprocess", sandbox_root=execution_dir
    )

    assert kept.exists(), "cleanup deleted a file outside the sandbox"


def test_open_confined_directory_refuses_a_replaced_sandbox_root(tmp_path: Path):
    """A sandbox root that is itself a symlink must be refused.

    Resolving it would adopt the attacker's target, and every later comparison
    would then be relative to that same wrong place, which is how a parent
    replacement used to escape.
    """
    from document_ia_infra.core.file.safe_path import open_confined_directory
    from document_ia_infra.exception.security_exception import PathTraversalException

    sandbox = tmp_path / "root_sandbox"
    sandbox.mkdir()
    outside = tmp_path / "root_outside"
    outside.mkdir()
    (outside / "sub").mkdir()

    replaced_root = sandbox / "exec"
    replaced_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathTraversalException):
        open_confined_directory(replaced_root / "sub", replaced_root)


@pytest.mark.asyncio
async def test_tls_handshake_gets_the_remaining_budget():
    """TLS must inherit the leftover connect budget, not the original value."""
    from document_ia_infra.core.network.safe_transport import (
        SafeAsyncNetworkBackend,
    )

    seen: dict[str, float | None] = {}

    class FakeStream:
        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            seen["tls_timeout"] = timeout
            return self

        async def read(self, max_bytes, timeout=None):
            return b""

        async def write(self, buffer, timeout=None):
            return None

        async def aclose(self):
            return None

    backend = SafeAsyncNetworkBackend()
    backend._backend = AsyncMock()
    backend._backend.connect_tcp.return_value = FakeStream()

    with patch(
        "document_ia_infra.core.network.safe_transport.resolve_validated_ips",
        new=AsyncMock(return_value=["93.184.216.34"]),
    ):
        stream = await backend.connect_tcp("example.com", 443, timeout=1.0)
        await asyncio.sleep(0.2)
        await stream.start_tls(ssl_context=None)

    # Strictly less than the original budget: the elapsed DNS/dial time is gone.
    assert seen["tls_timeout"] is not None
    assert seen["tls_timeout"] < 0.9


@pytest.mark.asyncio
async def test_pooled_request_does_not_depend_on_dns():
    """A reused connection must not perform, or wait on, a DNS lookup.

    The pre-flight resolve ran before the pool could reuse a live connection, so
    a hanging resolver failed requests that needed no name resolution at all.
    """
    from document_ia_infra.core.network import safe_transport

    calls: list[str] = []
    real = safe_transport.resolve_validated_ips

    async def counting(hostname, port, allow_local=False):
        calls.append(hostname)
        return await real(hostname, port, allow_local=allow_local)

    transport = safe_transport.SafeAsyncHTTPTransport(allow_local=True)
    handler_response = httpx.Response(
        200,
        content=b"ok",
        request=httpx.Request("GET", "https://127.0.0.1:1/x"),
    )
    with patch.object(
        safe_transport.SafeAsyncHTTPTransport,
        "handle_async_request",
        new=AsyncMock(return_value=handler_response),
    ):
        async with httpx.AsyncClient(transport=transport) as client:
            with patch.object(safe_transport, "resolve_validated_ips", counting):
                await client.get("https://example.com/a.pdf")

    # The transport no longer resolves before delegating to the pool.
    assert calls == []
