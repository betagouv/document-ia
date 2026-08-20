import logging
from typing import Any, Optional

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_worker.core.ocr.base_http_ocr_service import BaseHttpOCRService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)

logger = logging.getLogger(__name__)


class ExtractContentHttpOcrStep(BaseStep[OcrResult]):
    preprocess_file_result: PreprocessFileResult | None = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        http_ocr_service: BaseHttpOCRService[Any],
    ):
        self.execution_id = main_workflow_context.execution_id
        self.http_ocr_service = http_ocr_service

    def get_context_result_key(self) -> str:
        return OcrResult.__name__

    async def _prepare_step(self):
        logger.info(f"Preparing ocr extraction step for file: {self.execution_id}")
        if self.preprocess_file_result is None:
            raise ValueError("PreprocessFileResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.preprocess_file_result = self._get_safe_workflow_context_key(
            PreprocessFileResult, context
        )

    async def _execute_internal(self) -> tuple[OcrResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None
        pages: list[OcrResultPage] = []
        for index, file_path in enumerate(
            self.preprocess_file_result.output_files_path, start=1
        ):
            result = await self.http_ocr_service.extract_text_from_image(
                file_path, "image/png"
            )
            if not result.success:
                raise RetryableException("HTTP OCR extraction failed")
            pages.append(
                OcrResultPage(
                    page_number=index,
                    text=result.content,
                    has_failed=False,
                )
            )
        return OcrResult(pages=pages), None
