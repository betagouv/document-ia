import logging
from pathlib import Path
from typing import Optional

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
    def __init__(self, main_workflow_context: MainWorkflowContext, file_info: FileInfo):
        super().__init__(main_workflow_context)
        self.file_info = file_info

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
        logger.info(f"Downloading file from S3: {self.file_info.s3_key}")
        file_path = Path(self.tmp_folder_path).joinpath(
            self.file_info.s3_key.get_secret_value().split("/")[-1]
        )
        s3_manager = S3Manager()
        try:
            s3_manager.download_file(
                self.file_info.s3_key.get_secret_value(), str(file_path)
            )
            logger.info(f"File downloaded successfully to: {file_path}")
            return (
                DownloadFileResult(
                    file_path=str(file_path), content_type=self.file_info.content_type
                ),
                None,
            )
        except S3AuthentificationException as e:
            logger.error("S3 authentication failed during file download.")
            raise RetryableException(e)

    async def cleanup(self, is_last_cleanup: bool = False):
        await super().cleanup(is_last_cleanup)
        if is_last_cleanup:
            logger.info(f"Cleaning up S3 files for execution: {self.execution_id}")
            s3_manager = S3Manager()
            try:
                s3_manager.delete_file(self.file_info.s3_key.get_secret_value())
                logger.info(f"S3 file deleted successfully: {self.file_info.s3_key}")
            except S3AuthentificationException as e:
                logger.error("S3 authentication failed during file deletion.", e)
                raise RuntimeError("Error while deleting S3 file") from e
