import logging
from pathlib import Path

from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.s3.s3_manager import S3Manager
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
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

    async def _execute_internal(self) -> DownloadFileResult:
        logger.info(f"Downloading file from S3: {self.file_info.s3_key}")
        file_path = Path(self.tmp_folder_path).joinpath(
            self.file_info.s3_key.split("/")[-1]
        )
        s3_manager = S3Manager()
        is_file_downloaded = s3_manager.download_file(
            self.file_info.s3_key, str(file_path)
        )
        if is_file_downloaded:
            logger.info(f"File downloaded successfully to: {file_path}")
            return DownloadFileResult(
                file_path=str(file_path), content_type=self.file_info.content_type
            )
        else:
            # TODO : add custom exception
            logger.error(f"Failed to download file from S3: {self.file_info.s3_key}")
            raise Exception(f"Failed to download file from S3: {self.file_info.s3_key}")
