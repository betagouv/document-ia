import logging
import json
from pathlib import Path
from typing import Optional, Any, cast

from pydantic import BaseModel

from document_ia_infra.data.document.schema.document_extraction import (
    DocumentExtraction,
)
from document_ia_infra.exception.openai_authentification_error import (
    OpenAIAuthentificationError,
)
from document_ia_infra.exception.retryable_exception import RetryableException
from document_ia_infra.openai.openai_manager import OpenAIManager
from document_ia_infra.data.workflow.dto.workflow_v2_dto import LLMExtractParams
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.workflow.main_workflow_context import (
    MainWorkflowContext,
    StepMetadata,
    StepLLMMetadata,
)
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMExtractionResult,
    LLMClassificationResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult
from document_ia_worker.workflow.step.llm_extract_document.settings import settings

logger = logging.getLogger(__name__)


class EmptyExtractionProperties(BaseModel):
    pass


class LLMExtractDocumentStep(BaseStep[LLMExtractionResult]):
    ocr_result: Optional[OcrResult] = None
    llm_classification_result: Optional[LLMClassificationResult] = None

    def __init__(
        self,
        main_workflow_context: MainWorkflowContext,
        model: str,
        temperature: float = 0.0,
        document_type_override: Optional[SupportedDocumentType] = None,
    ):
        self.execution_id = main_workflow_context.execution_id
        self.model = model
        self.temperature = temperature
        self.document_type_override = document_type_override
        self.openai_manager = OpenAIManager()
        self.prompt_service = PromptService()
        self.extraction_parameters = main_workflow_context.extraction_parameters

    @classmethod
    def from_v2_params(
        cls,
        main_workflow_context: MainWorkflowContext,
        params: LLMExtractParams,
    ) -> "LLMExtractDocumentStep":
        return cls(
            main_workflow_context=main_workflow_context,
            model=params.model.value,
            temperature=params.temperature,
            document_type_override=params.document_type,
        )

    def get_context_result_key(self) -> str:
        return LLMExtractionResult.__name__

    async def _prepare_step(self):
        logger.info(f"Preparing llm extraction step for execution: {self.execution_id}")
        if self.extraction_parameters is not None:
            logger.info(
                f"LLM extraction step will be overridden by the workflow parameters {self.extraction_parameters}"
            )
        if self.ocr_result is None:
            raise ValueError("OcrResultData not injected in context")
        has_document_type_override = self.document_type_override is not None
        if self.llm_classification_result is None and (
            not has_document_type_override
            and (
                self.extraction_parameters is None
                or self.extraction_parameters.document_type is None
            )
        ):
            raise ValueError(
                "LLMClassificationResult not injected in context or extraction parameters missing"
            )

    def inject_workflow_context(self, context: dict[str, Any]):
        self.ocr_result = self._get_safe_workflow_context_key(OcrResult, context)
        self.llm_classification_result = self._get_not_mandatory_workflow_context_key(
            LLMClassificationResult, context
        )

    def _save_openai_replay_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        document_type: SupportedDocumentType,
    ) -> None:
        replay_dir = Path(settings.OPENAI_REPLAY_PAYLOAD_SAVE_PATH)
        replay_dir.mkdir(parents=True, exist_ok=True)

        document_type_name = (
            document_type.value
            if hasattr(document_type, "value")
            else str(document_type)
        )
        replay_payload = {
            "execution_id": self.execution_id,
            "document_type": document_type_name,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        replay_file = replay_dir / f"{self.execution_id}.json"
        replay_file.write_text(
            json.dumps(replay_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("OpenAI replay payload saved to %s", replay_file)

    async def _execute_internal(self) -> tuple[LLMExtractionResult, StepMetadata]:
        assert self.ocr_result is not None

        document_type: Optional[SupportedDocumentType] = self.document_type_override

        if document_type is None and self.llm_classification_result is not None:
            document_type = SupportedDocumentType.from_str(
                self.llm_classification_result.data.document_type
            )
        elif document_type is None:
            if (
                self.extraction_parameters is not None
                and self.extraction_parameters.document_type is not None
            ):
                document_type = self.extraction_parameters.document_type

        if document_type is None:
            raise ValueError("Document type could not be determined for extraction")

        if document_type == SupportedDocumentType.AUTRE:
            logger.info(
                f"LLM extraction step skipped because classification returned {document_type.value}"
            )
            casted_extraction = cast(
                DocumentExtraction[BaseModel],
                DocumentExtraction[EmptyExtractionProperties](
                    type=document_type,
                    properties=EmptyExtractionProperties(),
                ),
            )
            return (
                LLMExtractionResult(data=casted_extraction),
                StepLLMMetadata(
                    step_name=self.__class__.__name__,
                    request_tokens=0,
                    response_tokens=0,
                ),
            )

        system_prompt, extract_class = self.prompt_service.get_extraction_prompt(
            document_type
        )

        user_prompt = ""
        for page in self.ocr_result.pages:
            user_prompt += f"{page.text}\n\n"

        if settings.OPENAI_REPLAY_PAYLOAD_SAVE_ENABLED:
            try:
                self._save_openai_replay_payload(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=self.model,
                    document_type=document_type,
                )
            except Exception as e:
                logger.warning(
                    "Failed to save OpenAI replay payload for execution %s: %s",
                    self.execution_id,
                    e,
                )

        # Build the parameterized GenericModel type at runtime. This is valid at runtime because
        # DocumentExtraction is a pydantic.generics.GenericModel. Static type checkers may warn.
        # Cast to Any/type to silence static analysis complaints about dynamically parameterized generics.

        response_class = cast(Any, DocumentExtraction[extract_class])

        try:
            (
                response,
                request_tokens,
                response_tokens,
            ) = await self.openai_manager.get_extraction_response(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_class=response_class,
                document_type=document_type,
                model=self.model,
                temperature=self.temperature,
            )
        except OpenAIAuthentificationError as e:
            raise RetryableException(e.message)

        return (
            LLMExtractionResult(
                data=response,
            ),
            StepLLMMetadata(
                step_name=self.__class__.__name__,
                request_tokens=request_tokens,
                response_tokens=response_tokens,
            ),
        )
