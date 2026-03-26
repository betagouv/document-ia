import logging
from typing import Optional, Any

import httpx

from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_worker.core.embedding.albert.albert_http_embedding_service import (
    AlbertHttpEmbeddingService,
)
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import LLMEmbeddingResult
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult

logger = logging.getLogger(__name__)


class LLMEmbeddingStep(BaseStep[LLMEmbeddingResult]):
    ocr_result: Optional[OcrResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id
        self.embedding_service = AlbertHttpEmbeddingService()

    def get_context_result_key(self) -> str:
        return LLMEmbeddingResult.__name__

    async def _prepare_step(self):
        logger.info(
            "Preparing llm embedding step for execution: %s",
            self.execution_id,
        )
        if self.ocr_result is None:
            raise ValueError("OcrResultData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.ocr_result = self._get_safe_workflow_context_key(OcrResult, context)

    async def _execute_internal(self) -> tuple[LLMEmbeddingResult, StepMetadata]:
        assert self.ocr_result is not None

        pages = self.ocr_result.pages
        embeddings_by_page: list[list[float]] = [[] for _ in pages]
        indexed_inputs: list[tuple[int, str]] = []

        for index, page in enumerate(pages):
            if page.text is None or page.text.strip() == "":
                continue
            indexed_inputs.append((index, page.text))

        if not indexed_inputs:
            return (
                LLMEmbeddingResult(embeddings_by_page=embeddings_by_page),
                StepMetadata(step_name=self.__class__.__name__, execution_time=0),
            )

        inputs = [text for _, text in indexed_inputs]

        try:
            response = await self.embedding_service.create_embeddings(
                input_data=inputs,
            )
        except httpx.HTTPError as exc:
            logger.error(
                "Embedding HTTP call failed for execution %s: %s",
                self.execution_id,
                exc,
            )
            raise RetryableException(str(exc))

        for item in response.data:
            if item.index >= len(indexed_inputs):
                raise ValueError("Embedding response index out of range")
            page_index, _ = indexed_inputs[item.index]
            embeddings_by_page[page_index] = item.embedding

        return (
            LLMEmbeddingResult(embeddings_by_page=embeddings_by_page),
            StepMetadata(step_name=self.__class__.__name__, execution_time=0),
        )
