import logging
from typing import Optional, Any

from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
)
from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_worker.core.prompt.prompt_configuration import (
    GENERIC_CLASSIFICATION_MODEL,
)
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
    StepLLMMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMClassificationResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult

logger = logging.getLogger(__name__)


class LLMClassifyDocumentStep(BaseStep[LLMClassificationResult]):
    ocr_result: Optional[OcrResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext, model: str):
        self.execution_id = main_workflow_context.execution_id
        self.model = model
        self.openai_manager = OpenAIManager()
        self.prompt_service = PromptService()

    def get_context_result_key(self) -> str:
        return LLMClassificationResult.__name__

    async def _prepare_step(self):
        logger.info(
            f"Preparing llm classification step for execution: {self.execution_id}"
        )
        if self.ocr_result is None:
            raise ValueError("OcrResultData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.ocr_result = self._get_safe_workflow_context_key(OcrResult, context)

    async def _execute_internal(self) -> tuple[LLMClassificationResult, StepMetadata]:
        assert self.ocr_result is not None

        system_prompt = self.prompt_service.get_classification_prompt(
            GENERIC_CLASSIFICATION_MODEL
        )
        user_prompt = ""
        for page in self.ocr_result.pages:
            user_prompt += f"{page.text}\n\n"

        try:
            (
                response,
                request_token,
                response_token,
            ) = await self.openai_manager.get_classification_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_class=DocumentClassification,
                model=self.model,
            )
        except OpenAIAuthentificationError as e:
            raise RetryableException(e.message)

        return (
            LLMClassificationResult(data=response),
            StepLLMMetadata(
                step_name=self.__class__.__name__,
                request_tokens=request_token,
                response_tokens=response_token,
            ),
        )
