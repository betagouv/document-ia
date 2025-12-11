import logging
from typing import Any, Optional

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_worker.core.nanonets.nanonets_service import NanonetsService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.download_file_result import (
    DownloadFileResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

logger = logging.getLogger(__name__)


class ExtractContentNanonetsOcrStep(BaseStep[OcrResult]):
    download_file_result: Optional[DownloadFileResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id

    def get_context_result_key(self) -> str:
        return OcrResult.__name__

    async def _prepare_step(self):
        logger.info(f"Preparing ocr extraction step for file: {self.execution_id}")
        if self.download_file_result is None:
            raise ValueError("DownloadFileReturnData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(DownloadFileResult.__name__)
        if not_typed_data is None or not isinstance(not_typed_data, DownloadFileResult):
            raise ValueError("DownloadFileResult not found in context")
        self.download_file_result = not_typed_data

    async def _execute_internal(self) -> tuple[OcrResult, Optional[StepMetadata]]:
        assert self.download_file_result is not None
        nanonets_service = NanonetsService()
        result = await nanonets_service.extract_text_from_image(
            self.download_file_result.file_path
        )
        if not result.success:
            raise RetryableException("Nanonets OCR extraction failed")
        return OcrResult(
            pages=[OcrResultPage(page_number=1, text=result.content, has_failed=False)]
        ), None