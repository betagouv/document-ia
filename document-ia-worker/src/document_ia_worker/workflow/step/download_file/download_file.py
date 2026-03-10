import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4
from email.message import Message
from urllib.parse import urlparse

import httpx
import magic

from document_ia_infra.core.file.file_settings import file_settings
from document_ia_infra.core.file.file_util import validate_file_extension
from document_ia_infra.core.model.file_info import FileInfo
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
        file_info: Optional[FileInfo],
        file_url: Optional[str] = None,
    ):
        super().__init__(main_workflow_context)
        self.file_info = file_info
        self.file_url = file_url

    def get_context_result_key(self) -> str:
        return DownloadFileResult.__name__

    async def _prepare_step(self):
        logger.info(f"Preparing download step for file: {self.file_info}")
        tmp_dir = Path(self.tmp_folder_path)
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created temp directory: {tmp_dir}")
        else:
            logger.debug(f"Temp directory already exists: {tmp_dir}")

    async def _execute_internal(
        self,
    ) -> tuple[DownloadFileResult, Optional[StepMetadata]]:
        if self.file_info is not None:
            return await self._handle_s3_file(self.file_info)
        elif self.file_url is not None:
            return await self._handle_file_url(self.file_url)
        else:
            raise ValueError("No file information or URL provided for download.")

    async def _handle_file_url(self, file_url: str):
        logger.info(f"Downloading file from URL: {file_url}")
        tmp_dir = Path(self.tmp_folder_path)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        CHUNK_SIZE = 8192
        MAGIC_BUFFER_SIZE = 2048  # Libmagic needs approx 2KB for accurate detection

        filename: Optional[str] = None
        tmp_file: Path = Path()
        success = False

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", file_url) as response:
                    response.raise_for_status()

                    content_disposition = response.headers.get("Content-Disposition")
                    if content_disposition:
                        msg = Message()
                        msg.add_header("Content-Disposition", content_disposition)
                        filename = msg.get_filename()

                    if not filename:
                        parsed = urlparse(file_url)
                        path_name = Path(parsed.path).name
                        filename = (
                            path_name
                            if path_name and validate_file_extension(path_name)
                            else ""
                        )

                    temp_name = filename or "downloaded_file"
                    tmp_file = tmp_dir / temp_name

                    content_size = 0
                    mime_checked = False
                    detected_mime = None
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
                                    )  # pyright: ignore

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
                        detected_mime = magic.from_buffer(bytes(head_buffer), mime=True)  # pyright: ignore
                        if detected_mime not in file_settings.ALLOWED_MIME_TYPES:
                            raise ValueError(
                                f"Detected MIME type not allowed: {detected_mime}"
                            )
                        with open(tmp_file, "wb") as f:
                            f.write(head_buffer)

                    if not detected_mime:
                        detected_mime = magic.from_file(tmp_file, mime=True)  # pyright: ignore
                        if detected_mime not in file_settings.ALLOWED_MIME_TYPES:
                            raise ValueError(
                                f"Detected MIME type not allowed: {detected_mime}"
                            )

            extension = file_settings.ALLOWED_MIME_TYPES[detected_mime][0]

            if not filename:
                final_path = tmp_dir / f"{uuid4().hex}{extension}"
            else:
                valid_exts = file_settings.ALLOWED_MIME_TYPES[detected_mime]
                if not any(filename.endswith(ext) for ext in valid_exts):
                    final_path = tmp_file.with_suffix(extension)
                else:
                    final_path = tmp_dir / filename

            # Replace is atomic on POSIX
            tmp_file.replace(final_path)
            success = True

            return (
                DownloadFileResult(
                    file_path=str(final_path), content_type=detected_mime
                ),
                None,
            )

        except Exception as e:
            logger.error(f"Error handling file url: {e}")
            raise e

        finally:
            # Cleanup temp file if operation failed
            if not success and tmp_file and tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    async def _handle_s3_file(self, file_info: FileInfo):
        logger.info(f"Downloading file from S3: {file_info.s3_key}")
        file_path = Path(self.tmp_folder_path).joinpath(
            file_info.s3_key.get_secret_value().split("/")[-1]
        )
        s3_manager = S3Manager()
        try:
            s3_manager.download_file(
                file_info.s3_key.get_secret_value(), str(file_path)
            )
            logger.info(f"File downloaded successfully to: {file_path}")
            return (
                DownloadFileResult(
                    file_path=str(file_path), content_type=file_info.content_type
                ),
                None,
            )
        except S3AuthentificationException as e:
            logger.error("S3 authentication failed during file download.")
            raise RetryableException(e)

    async def cleanup(self, is_last_cleanup: bool = False):
        await super().cleanup(is_last_cleanup)
        if is_last_cleanup and self.file_info is not None:
            logger.info(f"Cleaning up S3 files for execution: {self.execution_id}")
            s3_manager = S3Manager()
            try:
                s3_manager.delete_file(self.file_info.s3_key.get_secret_value())
                logger.info(f"S3 file deleted successfully: {self.file_info.s3_key}")
            except S3AuthentificationException as e:
                logger.error("S3 authentication failed during file deletion.", e)
                raise RuntimeError("Error while deleting S3 file") from e
