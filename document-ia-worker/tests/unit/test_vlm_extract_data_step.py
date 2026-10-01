from datetime import UTC, datetime

import pytest
from document_ia_infra.data.workflow.dto.enums import VLMModel
from document_ia_infra.data.workflow.dto.workflow_v2_dto import VLMExtractParams
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.step_result.preprocess_file_result import (
    PreprocessFileResult,
)
from document_ia_worker.workflow.step.vlm_extract_data.vlm_extract_data import (
    VLMExtractDataStep,
)
from document_ia_schemas.cni import CNIModel


@pytest.mark.asyncio
async def test_vlm_step_keeps_one_conversation_for_ocr_classification_and_extraction(
    tmp_path,
):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-image")

    context = MainWorkflowContext(
        execution_id="execution-1",
        organization_id=None,
        start_time=datetime.now(UTC),
    )
    step = VLMExtractDataStep(
        context,
        VLMExtractParams(model=VLMModel.MISTRAL_MEDIUM_3_5),
    )
    step.inject_workflow_context(
        {PreprocessFileResult.__name__: PreprocessFileResult(output_files_path=[str(image_path)])}
    )

    class FakePromptService:
        def get_classification_prompt(self, document_type_list):
            assert document_type_list
            return "classification prompt"

        def get_extraction_prompt(self, document_type):
            return "extraction prompt", CNIModel

    class FakeOpenAIManager:
        def __init__(self):
            self.calls = []
            self.responses = [
                "OCR text",
            ]

        async def get_vlm_response(self, *, messages, model, temperature):
            self.calls.append([dict(message) for message in messages])
            return self.responses.pop(0), 1, 2

        async def get_vlm_typed_response(
            self, *, messages, response_class, model, temperature
        ):
            self.calls.append([dict(message) for message in messages])
            if response_class.__name__ == "DocumentClassification":
                return (
                    response_class(
                        document_type="cni", confidence=0.9, explanation="ok"
                    ),
                    '{"document_type":"cni","confidence":0.9,"explanation":"ok"}',
                    1,
                    2,
                )
            return (
                response_class(numero_document="42"),
                '{"numero_document":"42"}',
                1,
                2,
            )

    step.prompt_service = FakePromptService()
    step.openai_manager = FakeOpenAIManager()

    result, metadata = await step.execute()

    assert result.classification.document_type.value == "cni"
    assert result.extraction.properties.numero_document == "42"
    assert metadata.request_tokens == 3
    assert metadata.response_tokens == 6
    assert len(step.openai_manager.calls) == 3
    assert [message["role"] for message in step.openai_manager.calls[0]] == [
        "system",
        "user",
    ]
    assert [message["role"] for message in step.openai_manager.calls[1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [message["role"] for message in step.openai_manager.calls[2]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert step.openai_manager.calls[0][1]["content"][0]["text"].startswith(
        "Effectue l'OCR"
    )
    assert "<<<<<<<<<<4" in step.openai_manager.calls[2][-1]["content"]
    assert "images originales" in step.openai_manager.calls[2][-1]["content"]
