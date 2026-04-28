import logging
from typing import Optional, Any

import httpx

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.core.ocr_type import OCRType
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import LLMEmbeddingResult
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)

logger = logging.getLogger(__name__)


class LLMEmbeddingMultimodalStep(BaseStep[LLMEmbeddingResult]):
    """
    Step that generates multimodal embeddings using a local Jina server.
    Instead of text, it sends images of the document pages.
    """

    preprocess_file_result: Optional[PreprocessFileResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id
        # Local Jina server endpoint
        self.jina_endpoint = "http://localhost:8093/embed"

    def get_context_result_key(self) -> str:
        # We still return LLMEmbeddingResult as main result,
        # but we also want to inject OcrResult in the context for downstream steps.
        return LLMEmbeddingResult.__name__

    async def _prepare_step(self):
        logger.info(
            "Preparing multimodal llm embedding step for execution: %s",
            self.execution_id,
        )
        if self.preprocess_file_result is None:
            raise ValueError("PreprocessFileResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.preprocess_file_result = self._get_safe_workflow_context_key(
            PreprocessFileResult, context
        )

    async def _execute_internal(self) -> tuple[LLMEmbeddingResult, StepMetadata]:
        assert self.preprocess_file_result is not None

        image_paths = self.preprocess_file_result.output_files_path
        embeddings_by_page: list[list[float]] = [[] for _ in image_paths]
        ocr_pages: list[OcrResultPage] = []

        async with httpx.AsyncClient(timeout=120.0) as client:
            for index, image_path in enumerate(image_paths):
                # Add entry to ocr_pages for consistency
                ocr_pages.append(
                    OcrResultPage(page_number=index + 1, text="", has_failed=False)
                )

                try:
                    logger.info(
                        "Generating multimodal embedding for page %s of execution %s",
                        index + 1,
                        self.execution_id,
                    )

                    with open(image_path, "rb") as f:
                        files = {"file": (image_path, f, "image/jpeg")}
                        response = await client.post(self.jina_endpoint, files=files)

                    if response.status_code != 200:
                        logger.error(
                            "Multimodal embedding failed for execution %s page %s: %s",
                            self.execution_id,
                            index + 1,
                            response.text,
                        )
                        ocr_pages[-1].has_failed = True
                        continue

                    data = response.json()
                    if isinstance(data, list):
                        embeddings_by_page[index] = data
                    elif isinstance(data, dict) and "embedding" in data:
                        embeddings_by_page[index] = data["embedding"]
                    else:
                        embeddings_by_page[index] = data

                except (httpx.HTTPError, IOError) as exc:
                    logger.error(
                        "Multimodal embedding call failed for execution %s page %s: %s",
                        self.execution_id,
                        index + 1,
                        exc,
                    )
                    ocr_pages[-1].has_failed = True
                    if isinstance(exc, httpx.HTTPError):
                        raise RetryableException(str(exc))
                    continue

        # Create the multimodal OCR result to satisfy downstream dependencies (like embedding_classify_document)
        self.multimodal_ocr_result = OcrResult(pages=ocr_pages, ocr_type=OCRType.JINA)

        return (
            LLMEmbeddingResult(
                embeddings_by_page=embeddings_by_page, isMultiModal=True
            ),
            StepMetadata(step_name=self.__class__.__name__, execution_time=0),
        )

    async def execute(self) -> tuple[LLMEmbeddingResult, StepMetadata]:
        # Overriding execute to also put OcrResult in the context
        result, metadata = await super().execute()
        return result, metadata

    def post_execute(self, context: dict[str, Any], result: LLMEmbeddingResult):
        # Inject OcrResult into context so following steps see JINA_MULTIMODAL as ocr_type
        context[OcrResult.__name__] = self.multimodal_ocr_result
