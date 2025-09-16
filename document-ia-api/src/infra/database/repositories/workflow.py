import json
import logging
from pathlib import Path
from typing import Optional, List

from schemas.workflow import WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowRepository:
    """Repository for managing workflow definitions from JSON file."""

    def __init__(self, workflows_file_path: Optional[str] = None):
        """
        Initialize the workflow repository.

        Args:
            workflows_file_path: Path to the workflows JSON file.
                                If None, uses default path.
        """
        if workflows_file_path is None:
            # Default path relative to the project root
            current_dir = Path(__file__).parent
            # Go up from: src/infra/database/repositories/ to src/
            src_dir = current_dir.parent.parent.parent
            workflows_file_path = str(src_dir / "data" / "workflows.json")

        self.workflows_file_path = Path(workflows_file_path)

    async def get_workflow_by_id(
        self, workflow_id: str
    ) -> Optional[WorkflowDefinition]:
        """
        Retrieve a workflow definition by its ID.

        Args:
            workflow_id: The unique identifier of the workflow

        Returns:
            WorkflowDefinition if found, None otherwise

        Raises:
            FileNotFoundError: If workflows file doesn't exist
            json.JSONDecodeError: If JSON file is malformed
            ValueError: If workflow data is invalid
        """
        try:
            workflows = await self._load_workflows()

            for workflow in workflows:
                if workflow.id == workflow_id:
                    logger.debug(f"Found workflow: {workflow_id}")
                    return workflow

            logger.warning(f"Workflow not found: {workflow_id}")
            return None

        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            # Re-raise these specific exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error retrieving workflow {workflow_id}: {e}")
            raise

    async def get_all_workflows(self) -> List[WorkflowDefinition]:
        """
        Retrieve all workflow definitions.

        Returns:
            List of all workflow definitions
        """
        try:
            workflows = await self._load_workflows()
            logger.debug(f"Retrieved {len(workflows)} workflows")
            return workflows

        except Exception as e:
            logger.error(f"Error retrieving all workflows: {e}")
            return []

    async def _load_workflows(self) -> List[WorkflowDefinition]:
        """
        Load workflows from JSON file.

        Returns:
            List of workflow definitions

        Raises:
            FileNotFoundError: If workflows file doesn't exist
            json.JSONDecodeError: If JSON file is malformed
            ValueError: If workflow data is invalid
        """
        try:
            # Check if file exists
            if not self.workflows_file_path.exists():
                raise FileNotFoundError(
                    f"Workflows file not found: {self.workflows_file_path}"
                )

            # Load and parse JSON file
            with open(self.workflows_file_path, "r", encoding="utf-8") as f:
                workflows_data = json.load(f)

            # Validate and parse workflows
            workflows: list[WorkflowDefinition] = []
            for workflow_data in workflows_data:
                try:
                    workflow = WorkflowDefinition(**workflow_data)
                    workflows.append(workflow)
                except Exception as e:
                    logger.warning(f"Invalid workflow data skipped: {e}")
                    continue

            logger.info(
                f"Loaded {len(workflows)} workflows from {self.workflows_file_path}"
            )
            return workflows

        except FileNotFoundError as e:
            logger.error(f"Workflows file not found: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in workflows file: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error loading workflows: {e}")
            raise


# Global workflow repository instance
workflow_repository = WorkflowRepository()
