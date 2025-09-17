import logging
from typing import Optional, Any

from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_worker.core.prompt.model.DocumentClassification import (
    DocumentClassification,
)
from document_ia_worker.core.prompt.prompt_configuration import (
    SupportedDocumentCategory,
)
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import LLMResult
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult

logger = logging.getLogger(__name__)


class LLMClassifyDocumentStep(BaseStep[LLMResult]):
    ocr_result: Optional[OcrResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext):
        self.execution_id = main_workflow_context.execution_id
        self.openai_manager = OpenAIManager()
        self.prompt_service = PromptService()

    def get_context_result_key(self) -> str:
        return LLMResult.__name__

    async def _prepare_step(self):
        logger.info(
            f"Preparing llm classification step for execution: {self.execution_id}"
        )
        if self.ocr_result is None:
            raise ValueError("OcrResultData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        not_typed_data = context.get(OcrResult.__name__)
        if not_typed_data is None or not isinstance(not_typed_data, OcrResult):
            raise ValueError("OcrResultData not found in context")
        self.ocr_result = not_typed_data

    async def _execute_internal(self) -> LLMResult:
        assert self.ocr_result is not None
        system_prompt = self.prompt_service.get_classification_prompt(
            [SupportedDocumentCategory.IDENTIFICATION]
        )
        user_prompt = ""
        for page in self.ocr_result.pages:
            user_prompt += f"{page.text}\n\n"

        response = await self.openai_manager.generate_typped_response(
            system_prompt, user_prompt, DocumentClassification
        )
        logger.info(f"LLM classification response: {response}")
        return LLMResult(data=response)
