import json
from pathlib import Path

import pytest

from document_ia_infra.data.document.schema.document_classification import DocumentClassification
from document_ia_schemas import SupportedDocumentType
from document_ia_schemas.cni import CNIModel
from document_ia_worker.workflow.step.llm_extract_document.llm_extract_document import (
    LLMExtractDocumentStep,
)
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMExtractionResult,
    LLMClassificationResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT_PATH = FIXTURES_DIR / "ocr_result_cni.json"


class TestLLMExtract:
    @pytest.mark.skipif(not SNAPSHOT_PATH.exists(), reason="OCR snapshot not found")
    @pytest.mark.asyncio
    async def test_extract_with_cni_fixture_and_mocked_classification(self, monkeypatch, main_workflow_context):
        # Build OcrResult from snapshot
        data = json.loads(SNAPSHOT_PATH.read_text())
        pages = [OcrResultPage(**p) for p in data.get("pages", [])]
        assert pages, "OCR snapshot has no pages"
        ocr_result = OcrResult(pages=pages)

        # Mock classification result to 'cni'
        classification = DocumentClassification(
            explanation="static mock",
            document_type=SupportedDocumentType.CNI,
            confidence=0.99,
        )
        llm_classification_result = LLMClassificationResult(data=classification, request_tokens=1, response_tokens=1)

        class FakeOpenAIManager:
            async def get_extraction_response(
                    self,
                    system_prompt: str,
                    user_prompt: str,
                    response_class,
                    document_type: SupportedDocumentType,
                    model: str
            ):
                # Dans le step, response_class == DocumentExtraction[extract_class]
                # On reconstitue le inner_class exactement comme dans OpenAIManager
                inner_class = response_class.model_fields["properties"].annotation

                # On simule ce que _generate_typed_response ferait : un JSON de CNIModel
                cni_payload = {
                    "numero_document": "123456789012",
                    "nom": "DUPONT",
                    "prenom": "JEAN",
                    "lieu_naissance": "PARIS",
                    "nationalite": "Française",
                }

                # On parse comme dans `_generate_typed_response` : par nom de champ
                cni_model = inner_class.model_validate(cni_payload, by_name=True, by_alias=False)

                # Puis on reconstruit un DocumentExtraction comme dans get_extraction_response
                doc_extraction = response_class(
                    type=document_type,
                    properties=cni_model,
                )

                return doc_extraction, 1, 1

        monkeypatch.setattr(
            "document_ia_worker.workflow.step.llm_extract_document.llm_extract_document.OpenAIManager",
            lambda: FakeOpenAIManager(),
        )

        # Build context and run the extract step
        step = LLMExtractDocumentStep(main_workflow_context=main_workflow_context, model="dummy-model")

        step.inject_workflow_context(
            {
                OcrResult.__name__: ocr_result,
                LLMClassificationResult.__name__: llm_classification_result,
            }
        )

        result, metadata = await step.execute()

        # Assertions
        assert metadata.step_name == "LLMExtractDocumentStep"
        assert metadata.execution_time >= 0

        assert isinstance(result, LLMExtractionResult)
        data_out = result.data
        assert getattr(data_out, "type", None) == "cni"

        props = getattr(data_out, "properties", None)
        assert props is not None
        assert isinstance(props, CNIModel)
        assert props.numero_document == "123456789012"
        assert props.nom == "DUPONT" and props.prenom == "JEAN"
