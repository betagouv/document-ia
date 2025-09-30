import logging
from datetime import datetime, UTC
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import WorkflowExecutionStartedEvent
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.service.event_store_service import EventStoreService
from document_ia_worker.exception.no_event_attached_to_execution_exception import (
    NoEventAttachedToExecutionException,
)
from document_ia_worker.exception.workflow_not_found_exception import (
    WorkflowNotFoundException,
)
from document_ia_worker.exception.workflow_step_exception import WorkflowStepException
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
from document_ia_worker.workflow.step.save_classification_workflow_result.save_classification_workflow_result import (
    SaveClassificationWorkflowResultStep,
)

logger = logging.getLogger(__name__)


class WorkflowManager:
    event_dto: Optional[EventDTO]
    event_data: Optional[WorkflowExecutionStartedEvent]
    step_list: list[BaseStep[Any]]
    workflow_context: dict[str, Any]
    main_workflow_context: Optional[MainWorkflowContext]

    def __init__(self, message: WorkflowExecutionMessage, retry_count: int):
        self.message = message
        logger.info("New workflow_manager instance")
        # We can't use the singleton here because we need a new session for each thread
        self.database_manager = DatabaseManager()

        # Instance-scoped state to avoid cross-thread leakage
        self.retry_count = retry_count
        self.event_dto = None
        self.event_data = None
        self.step_list = []
        self.workflow_context = {}
        self.main_workflow_context = None

    async def start(self):
        self.main_workflow_context = MainWorkflowContext(
            execution_id=self.message.workflow_execution_id,
            start_time=datetime.now(UTC),
        )
        async with self.database_manager.local_session() as session:
            try:
                await self._prepare_workflow(session)
                self.event_data = self._parse_start_event()
                self._prepare_executor(session)
                await self._execute_workflow()
            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                # We use the WorkflowStepException to know in which step the error happened
                # and we dispatch the inner exception to have the original exception
                await self._save_failure_event(session, e)
                if isinstance(e, WorkflowStepException):
                    raise e.inner_exception
                else:
                    raise e
            finally:
                await session.commit()

    async def _prepare_workflow(self, session: AsyncSession):
        try:
            logger.info(f"Preparing workflow {self.message.workflow_execution_id}")
            event_dto = await EventRepository(
                session
            ).get_created_event_if_execution_not_completed_or_failed(
                self.message.workflow_execution_id
            )
            if event_dto is None:
                logger.error(
                    f"No events found that match a new execution {self.message.workflow_execution_id}"
                )
                raise NoEventAttachedToExecutionException(
                    self.message.workflow_execution_id
                )

            self.event_dto = event_dto
            self.workflow = await workflow_repository.get_workflow_by_id(
                event_dto.workflow_id
            )

            if self.workflow is None:
                logger.error(f"Workflow {event_dto.workflow_id} not found")
                raise WorkflowNotFoundException(self.message.workflow_execution_id)

        except Exception as e:
            # We catch all exceptions here to wrap them in a WorkflowStepException
            raise WorkflowStepException("prepare_workflow", e)

    def _prepare_executor(self, session: AsyncSession):
        try:
            if (
                self.workflow is None
                or self.event_dto is None
                or self.event_data is None
                or self.main_workflow_context is None
            ):
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
                    self.step_list.append(
                        PreprocessFileStep(self.main_workflow_context)
                    )
                if step == "extract_content_ocr":
                    self.step_list.append(
                        ExtractContentOcrStep(self.main_workflow_context)
                    )
                if step == "llm_classify_document":
                    self.step_list.append(
                        LLMClassifyDocumentStep(
                            self.main_workflow_context, self.workflow.llm_model
                        )
                    )
                if step == "save_classification_workflow_result":
                    self.step_list.append(
                        SaveClassificationWorkflowResultStep(
                            self.main_workflow_context, self.workflow.id, session
                        )
                    )
        except Exception as e:
            raise WorkflowStepException("prepare_executor", e)

    def _parse_start_event(self):
        try:
            if self.workflow is None or self.event_dto is None:
                raise Exception("Workflow or event not prepared")
            try:
                return WorkflowExecutionStartedEvent(**self.event_dto.event)
            except Exception as e:
                logger.error(
                    f"Failed to parse start event for execution {self.message.workflow_execution_id}: {e}"
                )
                raise
        except Exception as e:
            raise WorkflowStepException("parse_start_event", e)

    async def _execute_workflow(self):
        if len(self.step_list) == 0:
            raise WorkflowStepException(
                "execute_workflow", Exception("No workflow steps found")
            )
        if self.main_workflow_context is None:
            raise WorkflowStepException(
                "execute_workflow", Exception("Main workflow context not initialized")
            )
        try:
            for step in self.step_list:
                try:
                    logger.info(f"Executing step {step.__class__.__name__}")
                    step.inject_workflow_context(self.workflow_context)
                    result = await step.execute()
                    self.workflow_context[step.get_context_result_key()] = result
                    self.main_workflow_context.number_of_step_executed = (
                        self.main_workflow_context.number_of_step_executed + 1
                    )
                except Exception as e:
                    raise WorkflowStepException(step.__class__.__name__, e)
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

    async def _save_failure_event(self, db: AsyncSession, exception: Exception):
        if self.workflow is None or self.event_dto is None:
            raise Exception("Workflow or event not prepared")

        error_message: Optional[str] = None
        failed_step: Optional[str] = None

        if isinstance(exception, WorkflowStepException):
            logger.info(f"Saving failure event in step : {exception.step_name}")
            error_message = str(exception.inner_exception)
            failed_step = exception.step_name

        # Détermine l'exception à reporter (inner si disponible)
        inner_exc = (
            exception.inner_exception
            if isinstance(exception, WorkflowStepException)
            else exception
        )

        # Type d'erreur
        error_type = (
            RetryableException.__name__
            if isinstance(inner_exc, RetryableException)
            else inner_exc.__class__.__name__
        )

        # Message d'erreur
        final_error_message = (
            error_message if error_message is not None else str(inner_exc)
        )

        # Étape échouée
        final_failed_step = failed_step if failed_step is not None else "unknown"

        await EventStoreService(db).emit_workflow_failed(
            workflow_id=self.workflow.id,
            execution_id=self.event_dto.execution_id,
            error_type=error_type,
            error_message=final_error_message,
            failed_step=final_failed_step,
            retry_count=self.retry_count,
        )
