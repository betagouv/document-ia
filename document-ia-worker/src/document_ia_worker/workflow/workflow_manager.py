import logging
from datetime import datetime, UTC
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.event_dto import EventDTO
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
    ClassificationParameters,
    ExtractionParameters,
)
from document_ia_infra.data.webhook.repository.webhook_repository import (
    WebHookRepository,
)
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowDTO
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.redis.model.webhook_message import WebHookMessage
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.publisher import Publisher
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.service.event_store_service import EventStoreService
from document_ia_worker.core.aggregator_log import (
    setup_logging_worker,
    execution_id_var,
    agg_buffer_var,
    start_time_var,
    handle_finish_execution,
)
from document_ia_worker.core.ocr.deepseek.deepseek_http_ocr_service import (
    DeepSeekHttpHttpOcrService,
)
from document_ia_worker.core.ocr.marker.marker_http_ocr_service import (
    MarkerHttpHttpOcrService,
)
from document_ia_worker.core.ocr.mistral.mistral_http_ocr_service import (
    MistralHttpOcrService,
)
from document_ia_worker.core.ocr.nanonets.nanonets_http_ocr_service import (
    NanonetsHttpHttpOcrService,
)
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
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    ExtractBarcode2DDocData,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_data import (
    ExtractBarcodeData,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_http_ocr import (
    ExtractContentHttpOcrStep,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr import (
    ExtractContentOcrStep,
)
from document_ia_worker.workflow.step.llm_classify_document.llm_classify_document import (
    LLMClassifyDocumentStep,
)
from document_ia_worker.workflow.step.llm_extract_document.llm_extract_document import (
    LLMExtractDocumentStep,
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
    main_workflow_context: Optional[MainWorkflowContext]
    workflow: Optional[WorkflowDTO]

    def __init__(
        self,
        message: WorkflowExecutionMessage,
        retry_count: int,
        is_last_retry: bool = False,
    ):
        self.message = message
        logger.info("New workflow_manager instance")

        # Instance-scoped state to avoid cross-thread leakage
        self.retry_count = retry_count
        self.is_last_retry = is_last_retry
        self.event_dto = None
        self.event_data = None
        self.step_list = []
        self.workflow_context = {}
        self.main_workflow_context = None
        self.workflow = None

        # Aggregated logging context init (per workflow execution)
        setup_logging_worker()
        self._agg_token_exec = execution_id_var.set(self.message.workflow_execution_id)
        self._agg_token_buf = agg_buffer_var.set([])
        self._agg_token_started_at = start_time_var.set(datetime.now(UTC))

        self._webhook_producer: Publisher[WebHookMessage] = Publisher(
            redis_settings.WEBHOOK_STREAM_NAME, RedisManager()
        )

    async def start(self):
        self.main_workflow_context = MainWorkflowContext(
            execution_id=self.message.workflow_execution_id,
            start_time=datetime.now(UTC),
            organization_id=None,
            steps_metadata=[],
        )
        need_to_notify_webhook = True
        is_success = True
        err_type: Optional[str] = None
        err_message: Optional[str] = None
        failed_step: Optional[str] = None
        local_database_manager = DatabaseManager(pool_size=1, max_overflow=1)
        try:
            async with local_database_manager.local_session() as session:
                try:
                    await self._prepare_workflow(session)
                    self.event_data = self._parse_start_event()
                    self._prepare_executor(session)
                    await self._execute_workflow()
                except Exception as e:
                    logger.error(f"Workflow execution failed: {e}")
                    is_success = False
                    # We use the WorkflowStepException to know in which step the error happened
                    # and we dispatch the inner exception to have the original exception
                    if isinstance(e, WorkflowStepException):
                        failed_step = e.step_name
                        inner_exc = e.inner_exception
                    else:
                        inner_exc = e
                    err_type = (
                        RetryableException.__name__
                        if isinstance(inner_exc, RetryableException)
                        else inner_exc.__class__.__name__
                    )
                    err_message = str(inner_exc)

                    # we need to notify the webhook for every not retryable exception or if it's the last retry
                    # By default the need_to_notify_webhook is True
                    # So if an exception is Retryable and it's not the last_retry we set it to False to skip the webhook notification
                    if (
                        WorkflowStepException.is_retryable_exception(e)
                        and not self.is_last_retry
                    ):
                        need_to_notify_webhook = False

                    await self._save_failure_event(session, e)
                    if isinstance(e, WorkflowStepException):
                        raise e.inner_exception
                    else:
                        raise e
                finally:
                    # Persist DB changes
                    await session.commit()
                    if need_to_notify_webhook:
                        await self._notify_webhook_execution_finished(session)
                    handle_finish_execution(
                        logger,
                        self.workflow.id if self.workflow else "unknown",
                        is_success,
                        self.retry_count,
                        self.workflow.steps if self.workflow else [],
                        self._agg_token_exec,
                        self._agg_token_buf,
                        self._agg_token_started_at,
                        err_type,
                        err_message,
                        failed_step,
                        self.main_workflow_context.steps_metadata,
                    )
        finally:
            # We destroy correctly the databaeManager
            try:
                await local_database_manager.dispose_async()
            except Exception as e:
                logger.error(f"Error while disposing local database manager: {e}")

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

            if self.main_workflow_context is not None:
                self.main_workflow_context.organization_id = event_dto.organization_id

                if self.event_dto.event["classification_parameters"] is not None:
                    self.main_workflow_context.classification_parameters = (
                        ClassificationParameters(
                            **self.event_dto.event["classification_parameters"]
                        )
                    )

                if self.event_dto.event["extraction_parameters"] is not None:
                    self.main_workflow_context.extraction_parameters = (
                        ExtractionParameters(
                            **self.event_dto.event["extraction_parameters"]
                        )
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
                            self.main_workflow_context,
                            self.event_data.s3_file_info,
                            self.event_data.file_url,
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
                if step == "extract_content_marker_ocr":
                    self.step_list.append(
                        ExtractContentHttpOcrStep(
                            self.main_workflow_context, MarkerHttpHttpOcrService()
                        )
                    )
                if step == "extract_content_mistral_ocr":
                    self.step_list.append(
                        ExtractContentHttpOcrStep(
                            self.main_workflow_context, MistralHttpOcrService()
                        )
                    )
                if step == "extract_content_nanonets_ocr":
                    self.step_list.append(
                        ExtractContentHttpOcrStep(
                            self.main_workflow_context, NanonetsHttpHttpOcrService()
                        )
                    )
                if step == "extract_content_deepseek_ocr":
                    self.step_list.append(
                        ExtractContentHttpOcrStep(
                            self.main_workflow_context, DeepSeekHttpHttpOcrService()
                        )
                    )
                if step == "extract_barcode_data":
                    self.step_list.append(ExtractBarcodeData())
                if step == "extract_barcode_2ddoc_data":
                    self.step_list.append(ExtractBarcode2DDocData())
                if step == "llm_classify_document":
                    self.step_list.append(
                        LLMClassifyDocumentStep(
                            self.main_workflow_context,
                            self.main_workflow_context.classification_parameters.llm_model
                            if (
                                self.main_workflow_context.classification_parameters
                                and self.main_workflow_context.classification_parameters.llm_model
                                is not None
                            )
                            else self.workflow.llm_model,
                        )
                    )
                if step == "llm_extract_data":
                    self.step_list.append(
                        LLMExtractDocumentStep(
                            self.main_workflow_context,
                            self.main_workflow_context.extraction_parameters.llm_model
                            if (
                                self.main_workflow_context.extraction_parameters
                                and self.main_workflow_context.extraction_parameters.llm_model
                                is not None
                            )
                            else self.workflow.llm_model,
                        )
                    )
                if step == "save_workflow_result":
                    self.step_list.append(
                        SaveWorkflowResultStep(
                            self.main_workflow_context,
                            self.workflow.id,
                            session,
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

    async def _notify_webhook_execution_finished(self, async_session: AsyncSession):
        if self.main_workflow_context is None:
            logger.warning(
                "Main workflow context is None, skipping webhook notification"
            )
            return

        if self.main_workflow_context.organization_id is None:
            logger.warning("Organization ID is None, skipping webhook notification")
            return
        try:
            logger.info(
                f"Notifying webhook for finished execution {self.main_workflow_context.execution_id} of organization {self.main_workflow_context.organization_id}"
            )
            webhook_repository = WebHookRepository(async_session)
            webhooks = await webhook_repository.list_webhooks_by_organization(
                self.main_workflow_context.organization_id
            )

            for webhook in webhooks:
                await self._webhook_producer.publish_message(
                    WebHookMessage(
                        webhook_id=webhook.id,
                        workflow_execution_id=self.main_workflow_context.execution_id,
                    )
                )
        except Exception as e:
            logger.error(
                f"Failed to notify webhook for finished execution {self.main_workflow_context.execution_id}: {e}"
            )

    async def _execute_workflow(self):
        is_last_cleanup = True
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
                    result, step_metadata = await step.execute()
                    self.workflow_context[step.get_context_result_key()] = result
                    self.main_workflow_context.number_of_step_executed = (
                        self.main_workflow_context.number_of_step_executed + 1
                    )
                    self.main_workflow_context.steps_metadata.append(step_metadata)
                except Exception as e:
                    raise WorkflowStepException(step.__class__.__name__, e)
        except Exception as e:
            # If the exception is retryable, and we have retries left, we don't do the last cleanup to prevent S3 files to be deleted
            if (
                WorkflowStepException.is_retryable_exception(e)
                and not self.is_last_retry
            ):
                is_last_cleanup = False

            logger.error(
                f"Failed to execute workflow {self.message.workflow_execution_id}: {e}"
            )
            raise e
        finally:
            logger.info(f"Cleaning up workflow {self.message.workflow_execution_id}")
            # We clean up the data in the reverse order because the first step need to be the last
            for step in reversed(self.step_list):
                await step.cleanup(is_last_cleanup)

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
            organization_id=self.event_dto.organization_id,
            error_type=error_type,
            error_message=final_error_message,
            failed_step=final_failed_step,
            retry_count=self.retry_count,
        )
