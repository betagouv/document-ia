import logging
from datetime import datetime, UTC
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowType
from document_ia_infra.service.event_store_service import EventStoreService
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.barcode_result import BarcodeResult
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMClassificationResult,
    LLMResult,
)

logger = logging.getLogger(__name__)


class SaveWorkflowResultStep(BaseStep[None]):
    llm_classification: Optional[LLMClassificationResult] = None
    llm_extraction_result: Optional[LLMResult] = None
    barcode_data: Optional[BarcodeResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        workflow_id: str,
        workflow_type: WorkflowType,
        database_session: AsyncSession,
    ):
        self.main_workflow_context = main_workflow_context
        self.execution_id = main_workflow_context.execution_id
        self.workflow_id = workflow_id
        self.database_session = database_session
        self.workflow_type = workflow_type
        self.event_service = EventStoreService(self.database_session)

    def get_context_result_key(self) -> str:
        return ""

    async def _prepare_step(self):
        logger.info(
            f"Preparing save workflow data step for execution: {self.execution_id}"
        )
        if self.llm_classification is None:
            raise ValueError("LLMResult not injected in context")
        if (
            self.workflow_type == WorkflowType.EXTRACTION
            and self.llm_extraction_result is None
        ):
            raise ValueError("LLM Extraction Result not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.llm_classification = self._get_safe_workflow_context_key(
            LLMClassificationResult, context
        )
        if self.workflow_type == WorkflowType.EXTRACTION:
            self.llm_extraction_result = self._get_safe_workflow_context_key(
                LLMResult, context
            )
        self.barcode_data = self._get_not_mandatory_workflow_context_key(
            BarcodeResult, context
        )

    async def _execute_internal(self) -> None:
        assert self.llm_classification is not None
        end_time = datetime.now(UTC)
        final_result: dict[str, Any] = {}
        if self.workflow_type == WorkflowType.CLASSIFICATION:
            final_result = self.llm_classification.data.model_dump(mode="json")
        if self.workflow_type == WorkflowType.EXTRACTION:
            assert self.llm_extraction_result is not None
            final_result = {
                "classification": self.llm_classification.data.model_dump(mode="json"),
                "extraction": self.llm_extraction_result.data.model_dump(mode="json"),
            }
        if self.barcode_data is not None:
            final_result["barcode_data"] = self.barcode_data.model_dump(mode="json")
        try:
            await self.event_service.emit_workflow_completed(
                workflow_id=self.workflow_id,
                execution_id=self.execution_id,
                final_result=final_result,
                total_processing_time_ms=int(
                    (end_time - self.main_workflow_context.start_time).total_seconds()
                    * 1000
                ),
                output_summary={},
                steps_completed=self.main_workflow_context.number_of_step_executed + 1,
            )
        except Exception as e:
            logger.error(f"Error during saving workflow result: {e}")
            raise
