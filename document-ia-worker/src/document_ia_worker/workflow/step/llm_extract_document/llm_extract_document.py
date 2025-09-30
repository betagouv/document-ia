import logging
from typing import Optional, Any, cast

from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_worker.core.prompt.model.document_extraction import DocumentExtraction
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMResult,
    LLMClassificationResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult

logger = logging.getLogger(__name__)


class LLMExtractDocumentStep(BaseStep[LLMResult]):
    ocr_result: Optional[OcrResult] = None
    llm_classification_result: Optional[LLMClassificationResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext, model: str):
        self.execution_id = main_workflow_context.execution_id
        self.model = model
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
        if self.llm_classification_result is None:
            raise ValueError("LLMClassificationResult not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.ocr_result = self._get_safe_workflow_context_key(OcrResult, context)
        self.llm_classification_result = self._get_safe_workflow_context_key(
            LLMClassificationResult, context
        )

    async def _execute_internal(self) -> LLMResult:
        assert self.ocr_result is not None
        assert self.llm_classification_result is not None

        system_prompt, extract_class = self.prompt_service.get_extraction_prompt(
            self.llm_classification_result.data.document_type
        )

        user_prompt = ""
        for page in self.ocr_result.pages:
            user_prompt += f"{page.text}\n\n"

        # Build the parameterized GenericModel type at runtime. This is valid at runtime because
        # DocumentExtraction is a pydantic.generics.GenericModel. Static type checkers may warn.
        # Cast to Any/type to silence static analysis complaints about dynamically parameterized generics.
        # noinspection PyTypeHints
        response_class = cast(Any, DocumentExtraction[extract_class])

        try:
            response = await self.openai_manager.generate_typed_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_class=response_class,
                model=self.model,
            )
        except OpenAIAuthentificationError as e:
            raise RetryableException(e.message)

        logger.debug(f"LLM extraction response: {response}")
        return LLMResult(data=response)
