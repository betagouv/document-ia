import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.llm_classify_document.llm_classify_document import (
    LLMClassifyDocumentStep,
)
from document_ia_worker.workflow.step.step_result.ocr_result import (
    OcrResult,
    OcrResultPage,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOT_PATH = FIXTURES_DIR / "ocr_result_cni.json"


class TestLLMClassificationIntegration:
    """Integration tests for LLM-based document classification using OCR results."""

    @pytest.mark.asyncio
    async def test_llm_classification_returns_cni_and_fields_non_empty(self):
        """Integration: reuse OCR snapshot (ocr_result.json), pass OcrResult to the LLM, and
        verify the JSON output with document_type == 'cni' and other fields non-empty.
        Skips if Albert credentials or snapshot are not available.
        """

        if not SNAPSHOT_PATH.exists():
            pytest.skip(
                "OCR snapshot not found. Generate it first (WRITE_SNAPSHOT=1 run) or commit tests/fixtures/ocr_result_cni.json."
            )

        # Rebuild OcrResult from snapshot
        data = json.loads(SNAPSHOT_PATH.read_text())
        pages = [OcrResultPage(**p) for p in data.get("pages", [])]
        assert pages, "OCR snapshot has no pages"
        ocr_result = OcrResult(pages=pages)

        # Build context and run LLM classification via Albert
        ctx = MainWorkflowContext(execution_id=str(uuid4()), start_time=datetime.now())
        model = os.getenv("ALBERT_MODEL", "albert-large")
        llm = LLMClassifyDocumentStep(main_workflow_context=ctx, model=model)
        llm.inject_workflow_context({OcrResult.__name__: ocr_result})
        llm_result = await llm.execute()

        # Validate JSON shape and expected category
        out = llm_result.data.model_dump()
        assert isinstance(out.get("document_type"), str)
        assert out["document_type"].strip().lower() == "cni"
        assert isinstance(out.get("explanation"), str) and out["explanation"].strip() != ""
        assert out.get("confidence") is not None and isinstance(out["confidence"], (int, float))

    @pytest.mark.asyncio
    async def test_llm_classification_tax_notice_not_cni(self):
        """Integration: simulate a French tax notice ("avis d'imposition") OCR content
        and ensure the LLM does NOT classify it as 'cni'. Also check other fields are non-empty.
        Skips if Albert credentials are not available.
        """
        # Simulated OCR text typical of a French tax notice
        tax_page_1 = OcrResultPage(
            page_number=1,
            text=(
                "Direction générale des Finances publiques\n"
                "Avis d'imposition - Impôt sur le revenu\n"
                "N° fiscal: 123 456 789\n"
                "Référence de l'avis: 2024 09 000000\n"
                "Nom: DUPONT Jean\n"
                "Adresse: 12 rue de la République 75001 Paris\n"
                "Montant de l'impôt: 1 234 €\n"
            ),
            has_failed=False,
        )
        tax_page_2 = OcrResultPage(
            page_number=2,
            text=(
                "Détail du calcul de l'impôt\n"
                "Revenus imposables, parts fiscales, prélèvements à la source\n"
                "Ce document est un avis d'imposition émis par la DGFiP\n"
            ),
            has_failed=False,
        )
        ocr_result = OcrResult(pages=[tax_page_1, tax_page_2])

        # Build context and run LLM classification via Albert
        ctx = MainWorkflowContext(execution_id=str(uuid4()), start_time=datetime.now())
        model = os.getenv("ALBERT_MODEL", "albert-large")
        llm = LLMClassifyDocumentStep(main_workflow_context=ctx, model=model)
        llm.inject_workflow_context({OcrResult.__name__: ocr_result})
        llm_result = await llm.execute()

        # Validate JSON shape and ensure category is not 'cni'
        out = llm_result.data.model_dump()
        assert isinstance(out.get("document_type"), str)
        assert out["document_type"].strip().lower() != "cni", f"Unexpected 'cni' classification: {out['document_type']}"
        assert isinstance(out.get("explanation"), str) and out["explanation"].strip() != ""
        assert out.get("confidence") is not None and isinstance(out["confidence"], (int, float))
