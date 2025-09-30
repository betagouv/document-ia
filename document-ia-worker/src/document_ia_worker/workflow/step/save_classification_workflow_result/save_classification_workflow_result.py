import logging
from datetime import datetime, UTC
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.dto.event_type_enum import EventType
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.event.schema.event import WorkflowExecutionCompletedEvent
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMClassificationResult,
)

logger = logging.getLogger(__name__)


class SaveClassificationWorkflowResultStep(BaseStep[None]):
    llm_result: Optional[LLMClassificationResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        workflow_id: str,
        database_session: AsyncSession,
    ):
        self.main_workflow_context = main_workflow_context
        self.execution_id = main_workflow_context.execution_id
        self.workflow_id = workflow_id
        self.database_session = database_session
        self.event_repository = EventRepository(self.database_session)

    def get_context_result_key(self) -> str:
        return ""

    async def _prepare_step(self):
        logger.info(
            f"Preparing save workflow data step for execution: {self.execution_id}"
        )
        if self.llm_result is None:
            raise ValueError("LLMResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.llm_result = self._get_safe_workflow_context_key(
            LLMClassificationResult, context
        )

    async def _execute_internal(self) -> None:
        assert self.llm_result is not None
        end_time = datetime.now(UTC)
        event = WorkflowExecutionCompletedEvent(
            workflow_id=self.workflow_id,
            execution_id=self.execution_id,
            created_at=datetime.now(UTC),
            final_result=self.llm_result.data.model_dump(),
            total_processing_time_ms=int(
                int(
                    (end_time - self.main_workflow_context.start_time).total_seconds()
                    * 1000
                )
            ),
            output_summary={},
            steps_completed=self.main_workflow_context.number_of_step_executed + 1,
            version=1,
        )
        try:
            dto = await self.event_repository.put_event(
                self.workflow_id,
                self.execution_id,
                EventType.WORKFLOW_EXECUTION_COMPLETED,
                event.model_dump(mode="json"),
            )
            logger.info(f"Event added to store with ID: {dto.id}")

        except Exception as e:
            logger.error(f"Failed to save workflow result event: {e}")
            raise
