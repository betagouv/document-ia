import logging
from typing import Optional, Any

from pydantic import BaseModel

from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
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
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

logger = logging.getLogger(__name__)


class AnonymizedContentResponse(BaseModel):
    anonymisedContent: str


class LLMAnonymizeContentStep(BaseStep[OcrResult]):
    ocr_result: Optional[OcrResult] = None
    llm_classification_result: Optional[LLMClassificationResult] = None

    def __init__(self, main_workflow_context: MainWorkflowContext, model: str):
        self.execution_id = main_workflow_context.execution_id
        self.model = model
        self.openai_manager = OpenAIManager()
        self.prompt_service = PromptService()
        self.extraction_parameters = main_workflow_context.extraction_parameters

    def get_context_result_key(self) -> str:
        return OcrResult.__name__

    async def _prepare_step(self):
        logger.info(
            "Preparing llm anonymization step for execution: %s",
            self.execution_id,
        )
        if self.ocr_result is None:
            raise ValueError("OcrResultData not injected in context")

    def inject_workflow_context(self, context: dict[str, Any]):
        self.ocr_result = self._get_safe_workflow_context_key(OcrResult, context)
        self.llm_classification_result = self._get_not_mandatory_workflow_context_key(
            LLMClassificationResult, context
        )

    async def _execute_internal(self) -> tuple[OcrResult, StepMetadata]:
        assert self.ocr_result is not None

        document_type: Optional[SupportedDocumentType] = None

        if self.llm_classification_result is not None:
            document_type = SupportedDocumentType.from_str(
                self.llm_classification_result.data.document_type
            )
        else:
            if (
                self.extraction_parameters is not None
                and self.extraction_parameters.document_type is not None
            ):
                document_type = self.extraction_parameters.document_type

        if document_type is None:
            raise ValueError("Document type could not be determined for anonymization")

        system_prompt = self.prompt_service.get_anonymization_prompt(document_type)

        request_tokens_total = 0
        response_tokens_total = 0
        updated_pages: list[OcrResultPage] = []

        for page in self.ocr_result.pages:
            if page.text is None or page.text.strip() == "":
                updated_pages.append(page)
                continue

            try:
                (
                    response,
                    request_tokens,
                    response_tokens,
                ) = await self.openai_manager.get_classification_response(
                    system_prompt=system_prompt,
                    user_prompt=page.text,
                    response_class=AnonymizedContentResponse,
                    model=self.model,
                )
            except OpenAIAuthentificationError as e:
                raise RetryableException(e.message)

            request_tokens_total += request_tokens
            response_tokens_total += response_tokens

            updated_pages.append(
                page.model_copy(update={"text": response.anonymisedContent})
            )

        return (
            OcrResult(pages=updated_pages),
            StepLLMMetadata(
                step_name=self.__class__.__name__,
                request_tokens=request_tokens_total,
                response_tokens=response_tokens_total,
            ),
        )
