"""Comprehensive security test suite for DownloadFileStep and file confinement."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from document_ia_infra.core.file.file_settings import file_settings
from document_ia_infra.core.network.safe_transport import (
    SafeAsyncHTTPTransport,
    resolve_and_pin_ip,
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
