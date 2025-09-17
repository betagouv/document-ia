import asyncio
import logging

from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)

logger = logging.getLogger(__name__)


class WorkflowManager:
    def __init__(self, message: WorkflowExecutionMessage):
        self.message = message

    async def start(self):
        logger.info(f"Processing workflow message: {self.message}")
        await self._prepare_workflow()
        # Simuler le traitement du message
        await asyncio.sleep(1)
        logger.info(f"Working message {self.message} 20%")
        await asyncio.sleep(1)
        logger.info(f"Working message {self.message} 40%")
        await asyncio.sleep(1)
        logger.info(f"Working message {self.message} 60%")
        await asyncio.sleep(1)
        logger.info(f"Working message {self.message} 80%")
        await asyncio.sleep(1)
        logger.info(f"Finished processing workflow message: {self.message}")

    async def _prepare_workflow(self):
        # TODO load currentWorkflow from json data
        # worflow = await workflow_repository.get_workflow_by_id("document-analysis-v1")
        logger.info(f"Preparing workflow for message: {self.message}")
        await asyncio.sleep(1)
        return
