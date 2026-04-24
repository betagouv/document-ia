import logging
from typing import Any, Optional

import cv2
from cv2.typing import MatLike
from pytesseract import image_to_string  # pyright: ignore [reportUnknownVariableType]

from document_ia_infra.core.ocr_type import OCRType
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


class ExtractContentOcrStep(BaseStep[OcrResult]):
    preprocess_file_result: Optional[PreprocessFileResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id
        self.tesseract_psm = 11
        self.tesseract_oem = 1
        self.tesseract_lang = "fra"
        self.tesseract_config = f"--psm {self.tesseract_psm} --oem {self.tesseract_oem}"
        self.tesseract_timeout = 60  # seconds

    def get_context_result_key(self) -> str:
        return OcrResult.__name__

    async def _prepare_step(self):
        logger.info(f"Preparing ocr extraction step for file: {self.execution_id}")
        if self.preprocess_file_result is None:
            raise ValueError("DownloadFileReturnData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(PreprocessFileResult.__name__)
        if not_typed_data is None or not isinstance(
            not_typed_data, PreprocessFileResult
        ):
            raise ValueError("PreprocessFileReturnData not found in context")
        self.preprocess_file_result = not_typed_data

    async def _execute_internal(self) -> tuple[OcrResult, Optional[StepMetadata]]:
        assert self.preprocess_file_result is not None
        results: list[OcrResultPage] = []
        index = 1
        for file_path in self.preprocess_file_result.output_files_path:
            gray: Optional[MatLike] = None
            try:
                gray = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
                data: str = image_to_string(  # pyright: ignore [reportAssignmentType]
                    gray,
                    output_type="string",
                    config=self.tesseract_config,
                    lang=self.tesseract_lang,
                    timeout=self.tesseract_timeout,
                )
                logger.debug(f"OCR data extracted : {data}")
                results.append(
                    OcrResultPage(
                        text=data,
                        page_number=index,
                        has_failed=False,
                    )
                )
            # When there is an error during the OCR processing, we catch it and continue with the next page
            # It could be a timeout or any other error
            except Exception as e:
                logger.error(f"Error during OCR processing: {e}")
                results.append(
                    OcrResultPage(
                        text=None,
                        page_number=index,
                        has_failed=True,
                    )
                )
                continue
            finally:
                logger.info(f"OCR processing completed for file: {file_path}")
                del gray
                index += 1

        return OcrResult(pages=results, ocr_type=OCRType.TESSERACT), None
