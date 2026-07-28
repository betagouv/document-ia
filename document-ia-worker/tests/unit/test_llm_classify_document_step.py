import pytest
from document_ia_infra.data.document.schema.document_classification import (
    DocumentClassification,
)
from document_ia_infra.data.workflow.dto.enums import LLMModel
from document_ia_infra.data.workflow.dto.workflow_v2_dto import LLMClassifyParams

from document_ia_schemas import SupportedDocumentType
from document_ia_worker.core.prompt.prompt_configuration import GENERIC_CLASSIFICATION_MODEL
from document_ia_worker.workflow.main_workflow_context import StepLLMMetadata
from document_ia_worker.workflow.step.llm_classify_document.llm_classify_document import (
    LLMClassifyDocumentStep,
)
from document_ia_worker.workflow.step.step_result.ocr_result import OcrResult, OcrResultPage


@pytest.mark.asyncio
async def test_llm_classify_constructor_v1_compatibility(main_workflow_context):
    step = LLMClassifyDocumentStep(
        main_workflow_context=main_workflow_context,
        model="openweight-medium",
    )

    assert step.model == "openweight-medium"
    assert step.temperature == 0.0
    assert step.document_types_override is None


@pytest.mark.asyncio
async def test_llm_classify_from_v2_params_overrides_prompt_scope_and_temperature(
        main_workflow_context,
):
    params = LLMClassifyParams(
        model=LLMModel.ALBERT_SMALL,
        temperature=0.42,
        document_types=[SupportedDocumentType.CNI],
    )
    step = LLMClassifyDocumentStep.from_v2_params(
        main_workflow_context=main_workflow_context,
        params=params,
    )

    called: dict[str, object] = {}

    class FakePromptService:
        def get_classification_prompt(self, document_type_list):  # noqa: ANN001
            called["document_type_list"] = document_type_list
            return "system prompt"

    class FakeOpenAIManager:
        async def get_classification_response(
                self,
                *,
                system_prompt: str,
                user_prompt: str,
                response_class,
                model: str,
                temperature: float,
        ):
            called["model"] = model
            called["temperature"] = temperature
            return (
                DocumentClassification(
                    document_type=SupportedDocumentType.CNI,
                    explanation="ok",
                    confidence=0.99,
                ),
                3,
                5,
            )

    # pyrefly: ignore [bad-assignment]
    step.prompt_service = FakePromptService()
    # pyrefly: ignore [bad-assignment]
    step.openai_manager = FakeOpenAIManager()
    step.inject_workflow_context(
        {
            OcrResult.__name__: OcrResult(
                pages=[
                    OcrResultPage(
                        page_number=1,
                        text="Carte nationale d'identite",
                        has_failed=False,
                    )
                ]
            )
        }
    )

    result, metadata = await step.execute()

    assert result.data.document_type == SupportedDocumentType.CNI
    assert isinstance(metadata, StepLLMMetadata)
    assert metadata.request_tokens == 3
    assert metadata.response_tokens == 5
    assert called["model"] == "albert-small"
    assert called["temperature"] == 0.42
    assert called["document_type_list"] == [SupportedDocumentType.CNI]


@pytest.mark.asyncio
async def test_llm_classify_from_v2_params_with_all_uses_generic_document_types(
        main_workflow_context,
):
    params = LLMClassifyParams(
        model=LLMModel.ALBERT_SMALL,
        temperature=0.15,
        document_types="all",
    )
    step = LLMClassifyDocumentStep.from_v2_params(
        main_workflow_context=main_workflow_context,
        params=params,
    )

    called: dict[str, object] = {}

    class FakePromptService:
        def get_classification_prompt(self, document_type_list):  # noqa: ANN001
            called["document_type_list"] = document_type_list
            return "system prompt"

    class FakeOpenAIManager:
        async def get_classification_response(
                self,
                *,
                system_prompt: str,
                user_prompt: str,
                response_class,
                model: str,
                temperature: float,
        ):
            called["model"] = model
            called["temperature"] = temperature
            return (
                DocumentClassification(
                    document_type=SupportedDocumentType.CNI,
                    explanation="ok",
                    confidence=0.99,
                ),
                2,
                4,
            )

    # pyrefly: ignore [bad-assignment]
    step.prompt_service = FakePromptService()
    # pyrefly: ignore [bad-assignment]
    step.openai_manager = FakeOpenAIManager()
    step.inject_workflow_context(
        {
            OcrResult.__name__: OcrResult(
                pages=[
                    OcrResultPage(
                        page_number=1,
                        text="Texte OCR quelconque",
                        has_failed=False,
                    )
                ]
            )
        }
    )

    result, metadata = await step.execute()

    assert result.data.document_type == SupportedDocumentType.CNI
    assert isinstance(metadata, StepLLMMetadata)
    assert metadata.request_tokens == 2
    assert metadata.response_tokens == 4
    assert called["model"] == "albert-small"
    assert called["temperature"] == 0.15
    assert called["document_type_list"] == GENERIC_CLASSIFICATION_MODEL
