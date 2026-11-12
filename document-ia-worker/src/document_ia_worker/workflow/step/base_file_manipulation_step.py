import logging
from abc import ABC
from pathlib import Path
from typing import TypeVar

from document_ia_infra.core.file.safe_path import (
    get_execution_sandbox_root,
    safe_cleanup_directory,
    validate_safe_path,
)
from document_ia_infra.redis.progress_tracker import get_current_progress_tracker
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep

T = TypeVar("T")

logger = logging.getLogger(__name__)


class BaseFileManipulationStep(BaseStep[T], ABC):
    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        subfolder: str | None = None,
    ) -> None:
        self.execution_id = main_workflow_context.execution_id
        self.sandbox_root: Path = get_execution_sandbox_root(self.execution_id)

        if subfolder:
            # Validate that subfolder remains strictly confined within the sandbox root
            candidate_path = self.sandbox_root / subfolder
            self.tmp_folder_path: str = str(
                validate_safe_path(candidate_path, self.sandbox_root)
            )
        else:
            self.tmp_folder_path = str(self.sandbox_root)

    async def cleanup(self, is_last_cleanup: bool = False) -> None:
        tracker = get_current_progress_tracker()
        if tracker is not None and tracker.is_aborted:
            # Tentative avortée par le watchdog : un redémarrage du même
            # execution_id peut partager ce répertoire. Ne jamais supprimer des
            # fichiers qu'une tentative de remplacement est encore en train
            # d'utiliser.
            logger.info(
                "Skipping temp cleanup for aborted execution %s", self.execution_id
            )
            return

        target_path = Path(
            self.sandbox_root if is_last_cleanup else self.tmp_folder_path
        )
        logger.info(
            "Cleaning up directory: %s (is_last_cleanup=%s)",
            target_path,
            is_last_cleanup,
        )
        safe_cleanup_directory(target_path, sandbox_root=self.sandbox_root)
