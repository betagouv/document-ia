import logging
from abc import ABC
from pathlib import Path
from typing import TypeVar, Optional

from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep

T = TypeVar("T")

logger = logging.getLogger(__name__)


class BaseFileManipulationStep(BaseStep[T], ABC):
    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        subfolder: Optional[str] = None,
    ):
        self.execution_id = main_workflow_context.execution_id
        tmp_path = Path("/tmp/document_ia_worker.tmp").joinpath(self.execution_id)
        if subfolder:
            tmp_path = tmp_path.joinpath(subfolder)
        self.tmp_folder_path = str(tmp_path)

    async def cleanup(self):
        tmp_dir = Path(self.tmp_folder_path)
        if tmp_dir.exists() and tmp_dir.is_dir():
            for file in tmp_dir.iterdir():
                try:
                    file.unlink()
                    logger.info(f"Deleted temp file: {file}")
                except Exception as e:
                    logger.error(f"Failed to delete temp file {file}: {e}")
            try:
                tmp_dir.rmdir()
                logger.info(f"Deleted temp directory: {tmp_dir}")
            except Exception as e:
                logger.error(f"Failed to delete temp directory {tmp_dir}: {e}")
        else:
            logger.warning(
                f"Temp directory does not exist or is not a directory: {tmp_dir}"
            )
