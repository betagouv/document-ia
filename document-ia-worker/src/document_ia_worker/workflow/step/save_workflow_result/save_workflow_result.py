import logging
from datetime import datetime, UTC
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.schema.barcode import BarcodeVariant
from document_ia_infra.data.event.schema.workflow.workflow_execution_completed_event import (
    CompletedEventResult,
)
from document_ia_infra.service.event_store_service import EventStoreService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.barcode_result import BarcodeResult
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMClassificationResult,
    LLMExtractionResult,
)

logger = logging.getLogger(__name__)


class SaveWorkflowResultStep(BaseStep[None]):
    llm_classification: Optional[LLMClassificationResult] = None
    llm_extraction_result: Optional[LLMExtractionResult] = None
    barcode_data: Optional[BarcodeResult] = None

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
        self.event_service = EventStoreService(self.database_session)

    def get_context_result_key(self) -> str:
        return ""

    async def _prepare_step(self):
        logger.info(
            f"Preparing save workflow data step for execution: {self.execution_id}"
        )
        if self.llm_classification is None and self.llm_extraction_result is None:
            raise ValueError("LLMResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.llm_classification = self._get_not_mandatory_workflow_context_key(
            LLMClassificationResult, context
        )
        self.llm_extraction_result = self._get_not_mandatory_workflow_context_key(
            LLMExtractionResult, context
        )
        self.barcode_data = self._get_not_mandatory_workflow_context_key(
            BarcodeResult, context
        )

    async def _execute_internal(self) -> tuple[None, Optional[StepMetadata]]:
        end_time = datetime.now(UTC)
        final_result: CompletedEventResult = CompletedEventResult()

        if self.llm_classification is not None:
            final_result.classification = self.llm_classification.data

        if self.llm_extraction_result is not None:
            final_result.extraction = self.llm_extraction_result.data

        if self.barcode_data is not None:
            list_of_barcodes: list[BarcodeVariant] = []
            for page in self.barcode_data.pages:
                list_of_barcodes.extend(page.barcodes)
            final_result.barcodes = list_of_barcodes
        try:
            if self.main_workflow_context.organization_id is None:
                raise ValueError("Organization ID is not set in workflow context")
            await self.event_service.emit_workflow_completed(
                workflow_id=self.workflow_id,
                execution_id=self.execution_id,
                organization_id=self.main_workflow_context.organization_id,
                final_result=final_result,
                total_processing_time_ms=int(
                    (end_time - self.main_workflow_context.start_time).total_seconds()
                    * 1000
                ),
                output_summary={},
                steps_completed=self.main_workflow_context.number_of_step_executed + 1,
                workflow_metadata=self.main_workflow_context.steps_metadata,
            )
            return None, None
        except Exception as e:
            logger.error(f"Error during saving workflow result: {e}")
            raise
