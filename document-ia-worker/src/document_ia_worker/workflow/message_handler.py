import logging

from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_worker.workflow.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


async def process_message(message: WorkflowExecutionMessage, retry_count: int) -> None:
    logger.info(f"Received message: {message}")
    logger.info("Instantiate workflow manager")
    workflow_manager = WorkflowManager(message, retry_count)
    result = await workflow_manager.start()
    logger.info(f"Workflow manager finished with result: {result}")
    return result
