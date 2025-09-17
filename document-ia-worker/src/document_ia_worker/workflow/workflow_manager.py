import logging
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import WorkflowExecutionStartedEvent
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_worker.exception.no_event_attached_to_execution_exception import (
    NoEventAttachedToExecutionException,
)
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr import (
    ExtractContentOcrStep,
)
from document_ia_worker.workflow.step.llm_classify_document.llm_classify_document import (
    LLMClassifyDocumentStep,
)
from document_ia_worker.workflow.step.preprocess_file.preprocess_file import (
    PreprocessFileStep,
)
from document_ia_worker.workflow.step.save_workflow_result.save_workflow_result import (
    SaveWorkflowResultStep,
)

logger = logging.getLogger(__name__)


class WorkflowManager:
    event_dto: Optional[EventDTO]
    event_data: Optional[WorkflowExecutionStartedEvent]
    step_list: list[BaseStep[Any]]
    workflow_context: dict[str, Any]

    def __init__(self, message: WorkflowExecutionMessage):
        self.message = message
        logger.info("New workflow_manager instance")
        # We can't use the singleton here because we need a new session for each thread
        self.database_manager = DatabaseManager()
        self.main_workflow_context = MainWorkflowContext(
            self.message.workflow_execution_id
        )

        # Instance-scoped state to avoid cross-thread leakage
        self.event_dto = None
        self.event_data = None
        self.step_list = []
        self.workflow_context = {}

    async def start(self):
        logger.info(f"Processing workflow message: {self.message}")
        async with self.database_manager.local_session() as session:
            await self._prepare_workflow(session)
            self.event_data = self._parse_start_event()
            self._prepare_executor(session)
            await self._execute_workflow()
            await session.commit()

    async def _prepare_workflow(self, session: AsyncSession):
        logger.info(f"Preparing workflow {self.message.workflow_execution_id}")
        event_dto = await EventRepository(session).get_last_event_by_execution_id(
            self.message.workflow_execution_id
        )
        if event_dto is None:
            logger.error(
                f"No events found for execution {self.message.workflow_execution_id}"
            )
            raise NoEventAttachedToExecutionException(
                self.message.workflow_execution_id
            )
        if event_dto.event_type != EventType.WORKFLOW_EXECUTION_STARTED:
            logger.error(
                f"Last event for execution {self.message.workflow_execution_id} is not a start event"
            )
            # Make exception for event already started or finished
            raise NoEventAttachedToExecutionException(
                self.message.workflow_execution_id
            )
        self.event_dto = event_dto
        self.workflow = await workflow_repository.get_workflow_by_id(
            event_dto.workflow_id
        )
        if self.workflow is None:
            logger.error(f"Workflow {event_dto.workflow_id} not found")
            # TODO improve exception
            raise NoEventAttachedToExecutionException(
                self.message.workflow_execution_id
            )
        return

    def _prepare_executor(self, session: AsyncSession):
        if self.workflow is None or self.event_dto is None or self.event_data is None:
            raise Exception("Workflow or event not prepared")

        # Ensure a fresh step list per workflow execution
        self.step_list = []

        for step in self.workflow.steps:
            if step == "download_file":
                self.step_list.append(
                    DownloadFileStep(
                        self.main_workflow_context, self.event_data.file_info
                    )
                )
            if step == "preprocess_file":
                self.step_list.append(PreprocessFileStep(self.main_workflow_context))
            if step == "extract_content_ocr":
                self.step_list.append(ExtractContentOcrStep(self.main_workflow_context))
            if step == "llm_classify_document":
                self.step_list.append(
                    LLMClassifyDocumentStep(self.main_workflow_context)
                )
            if step == "save_results":
                self.step_list.append(
                    SaveWorkflowResultStep(
                        self.main_workflow_context, self.workflow.id, session
                    )
                )

    def _parse_start_event(self):
        if self.workflow is None or self.event_dto is None:
            raise Exception("Workflow or event not prepared")
        try:
            return WorkflowExecutionStartedEvent(**self.event_dto.event)
        except Exception as e:
            logger.error(
                f"Failed to parse start event for execution {self.message.workflow_execution_id}: {e}"
            )
            raise

    async def _execute_workflow(self):
        if len(self.step_list) == 0:
            raise Exception("No workflow steps found")
        try:
            for step in self.step_list:
                logger.info(f"Executing step {step.__class__.__name__}")
                step.inject_workflow_context(self.workflow_context)
                result = await step.execute()
                self.workflow_context[step.get_context_result_key()] = result
                self.main_workflow_context.number_of_step_executed = (
                    self.main_workflow_context.number_of_step_executed + 1
                )
        except Exception as e:
            logger.error(
                f"Failed to execute workflow {self.message.workflow_execution_id}: {e}"
            )
            raise e
        finally:
            logger.info(f"Cleaning up workflow {self.message.workflow_execution_id}")
            # We clean up the data in the reverse order because the first step need to be the last
            for step in reversed(self.step_list):
                await step.cleanup()
