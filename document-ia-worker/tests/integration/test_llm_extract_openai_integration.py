import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from document_ia_worker.core.prompt.model.document_classification import (
    DocumentClassification,
)
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.llm_extract_document.llm_extract_document import (
    LLMExtractDocumentStep,
)
from document_ia_worker.workflow.step.step_result.llm_result import (
    LLMResult,
    LLMClassificationResult,
)
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT_PATH = FIXTURES_DIR / "ocr_result_cni.json"


@pytest.mark.skipif(not SNAPSHOT_PATH.exists(), reason="Snapshot file does not exist")
@pytest.mark.asyncio
async def test_llm_extract_openai_real_call_with_cni_fixture():
    # Build OcrResult from snapshot
    data = json.loads(SNAPSHOT_PATH.read_text())
    pages = [OcrResultPage(**p) for p in data.get("pages", [])]
    assert pages, "OCR snapshot has no pages"
    ocr_result = OcrResult(pages=pages)

    # Inject a dummy classification result for CNI
    classification = DocumentClassification(
        explanation="integration test",
        document_type="cni",
        confidence=0.9,
    )
    llm_classification_result = LLMClassificationResult(data=classification)

    # Build context and run the extract step with a real OpenAI model
    ctx = MainWorkflowContext(execution_id=str(uuid4()), start_time=datetime.now())
    step = LLMExtractDocumentStep(main_workflow_context=ctx, model="albert-large")

    step.inject_workflow_context(
        {
            OcrResult.__name__: ocr_result,
            LLMClassificationResult.__name__: llm_classification_result,
        }
    )

    result = await step.execute()

    # Basic assertions on the returned data shape
    assert isinstance(result, LLMResult)
    out = result.data
    assert getattr(out, "type", None)
    props = getattr(out, "properties", None)
    assert props is not None, "expected properties in extracted result"
    # If the model succeeded guided by JSON schema, numero_document and identity fields should be present (strings)
    if hasattr(props, "numero_document"):
        assert isinstance(props.numero_document, str)
    if hasattr(props, "nom"):
        assert isinstance(props.nom, str)
    if hasattr(props, "prenom"):
        assert isinstance(props.prenom, str)
