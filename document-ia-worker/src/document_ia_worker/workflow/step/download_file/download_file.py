import logging
from pathlib import Path
from uuid import uuid4

import httpx
import magic

from document_ia_infra.core.file.file_settings import file_settings
from document_ia_infra.core.file.safe_path import validate_safe_path
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.core.network.safe_transport import SafeAsyncHTTPTransport
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.exception.s3_authentification_exception import (
    S3AuthentificationException,
)
from document_ia_infra.s3.s3_manager import S3Manager
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_file_manipulation_step import (
    BaseFileManipulationStep,
)
from document_ia_worker.workflow.step.step_result.download_file_result import (
    DownloadFileResult,
)

logger = logging.getLogger(__name__)


class DownloadFileStep(BaseFileManipulationStep[DownloadFileResult]):
    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        file_info: FileInfo | None = None,
        file_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(main_workflow_context)
        self.file_info = file_info
        self.file_url = file_url
        self._transport = transport

    def get_context_result_key(self) -> str:
        return DownloadFileResult.__name__

    async def _prepare_step(self) -> None:
        logger.info("Preparing download step for file: %s", self.file_info)
        tmp_dir = Path(self.tmp_folder_path)
        validate_safe_path(tmp_dir, self.sandbox_root)
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Created temp directory: %s", tmp_dir)
        else:
            logger.debug("Temp directory already exists: %s", tmp_dir)

    async def _execute_internal(
        self,
    ) -> tuple[DownloadFileResult, StepMetadata | None]:
        if self.file_info is not None:
            return await self._handle_s3_file(self.file_info)
        elif self.file_url is not None:
            return await self._handle_file_url(self.file_url)
        else:
            raise ValueError("No file information or URL provided for download.")

    async def _handle_file_url(self, file_url: str) -> tuple[DownloadFileResult, None]:
        logger.info("Downloading file from URL: %s", file_url)
        tmp_dir = Path(self.tmp_folder_path)
        validate_safe_path(tmp_dir, self.sandbox_root)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        CHUNK_SIZE = 8192
        MAGIC_BUFFER_SIZE = 2048  # Libmagic needs approx 2KB for accurate detection

        # Security F1: Generate purely random unique filename on worker side.
        # NEVER reuse Content-Disposition header or URL path name.
        random_token = uuid4().hex
        tmp_file: Path = validate_safe_path(
            tmp_dir / f"{random_token}.tmp", self.sandbox_root
        )
        final_path: Path | None = None
        success = False

        transport = (
            self._transport
            if self._transport is not None
            else SafeAsyncHTTPTransport(
                allow_http=file_settings.ALLOW_INSECURE_HTTP,
                allow_local=file_settings.ALLOW_LOCAL_NETWORK,
            )
        )

        try:
            async with httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                timeout=30.0,
            ) as client:
                async with client.stream("GET", file_url) as response:
                    response.raise_for_status()

                    content_size = 0
                    mime_checked = False
                    detected_mime: str | None = None
                    head_buffer = bytearray()

                    with open(tmp_file, "wb") as f:
                        async for chunk in response.aiter_bytes(CHUNK_SIZE):
                            content_size += len(chunk)

                            if content_size > file_settings.MAX_FILE_SIZE:
                                raise ValueError("File exceeds maximum allowed size")

                            if not mime_checked:
                                head_buffer.extend(chunk)

                                # Check MIME early to abort download if invalid
                                if len(head_buffer) >= MAGIC_BUFFER_SIZE:
                                    detected_mime = magic.from_buffer(
                                        bytes(head_buffer[:MAGIC_BUFFER_SIZE]),
                                        mime=True,
                                    )

                                    if (
                                        detected_mime
                                        not in file_settings.ALLOWED_MIME_TYPES
                                    ):
                                        raise ValueError(
                                            f"Detected MIME type not allowed: {detected_mime}"
                                        )

                                    f.write(head_buffer)
                                    head_buffer.clear()
                                    mime_checked = True
                            else:
                                f.write(chunk)

                    # Handle files smaller than the detection buffer
                    if not mime_checked and len(head_buffer) > 0:
                        detected_mime = magic.from_buffer(bytes(head_buffer), mime=True)
                        if detected_mime not in file_settings.ALLOWED_MIME_TYPES:
                            raise ValueError(
                                f"Detected MIME type not allowed: {detected_mime}"
                            )
                        with open(tmp_file, "wb") as f:
                            f.write(head_buffer)

                    if not detected_mime:
                        detected_mime = magic.from_file(  # pyright: ignore[reportUnknownMemberType]
                            str(tmp_file), mime=True
                        )
                        if detected_mime not in file_settings.ALLOWED_MIME_TYPES:
                            raise ValueError(
                                f"Detected MIME type not allowed: {detected_mime}"
                            )

            extension = file_settings.ALLOWED_MIME_TYPES[detected_mime][0]
            final_path = validate_safe_path(
                tmp_dir / f"{random_token}{extension}", self.sandbox_root
            )

            # Atomic replace within the confined sandbox
            tmp_file.replace(final_path)
            success = True

            return (
                DownloadFileResult(
                    file_path=str(final_path), content_type=detected_mime
                ),
                None,
            )

        except Exception as e:
            logger.error("Error handling file url: %s", e)
            raise e

        finally:
            # Cleanup temp file if operation failed
            if not success and tmp_file and tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    async def _handle_s3_file(
        self, file_info: FileInfo
    ) -> tuple[DownloadFileResult, None]:
        s3_key_value = file_info.s3_key.get_secret_value()
        logger.info("Downloading file from S3: %s", s3_key_value)

        # Security: Extract basename safely and confine to sandbox
        safe_basename = Path(s3_key_value).name
        if not safe_basename or safe_basename in {".", ".."}:
            safe_basename = f"{uuid4().hex}.bin"

        file_path = validate_safe_path(
            Path(self.tmp_folder_path) / f"{uuid4().hex}_{safe_basename}",
            self.sandbox_root,
        )

        s3_manager = S3Manager()
        try:
            s3_manager.download_file(s3_key_value, str(file_path))
            logger.info("File downloaded successfully to: %s", file_path)
            return (
                DownloadFileResult(
                    file_path=str(file_path),
                    content_type=file_info.content_type,
                ),
                None,
            )
        except S3AuthentificationException as e:
            logger.error("S3 authentication failed during file download.")
            raise RetryableException(e)

    async def cleanup(self, is_last_cleanup: bool = False) -> None:
        await super().cleanup(is_last_cleanup)
        if is_last_cleanup and self.file_info is not None:
            logger.info("Cleaning up S3 files for execution: %s", self.execution_id)
            s3_manager = S3Manager()
            try:
                s3_manager.delete_file(self.file_info.s3_key.get_secret_value())
                logger.info(
                    "S3 file deleted successfully: %s",
                    self.file_info.s3_key,
                )
            except S3AuthentificationException as e:
                logger.error("S3 authentication failed during file deletion: %s", e)
                raise RuntimeError("Error while deleting S3 file") from e
