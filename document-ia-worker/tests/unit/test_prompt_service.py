import json
import os
from pathlib import Path

import pytest

import document_ia_worker.core.prompt.prompt_service as ps_mod
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType


def _load_schema(doc_type: SupportedDocumentType) -> dict:
    base_dir = Path(ps_mod.__file__).resolve().parent
    schemas_dir = base_dir / "schemas"
    return json.loads((schemas_dir / f"document_{doc_type.value}_schema.json").read_text())

class TestPromptService:

    def test_classification_prompt_injects_document_categories_and_descriptions(self):
        service = PromptService()

        # Given three supported document types
        doc_types = [
            SupportedDocumentType.CNI,
            SupportedDocumentType.PASSEPORT,
            SupportedDocumentType.PERMIS_CONDUIRE,
        ]

        # When rendering the classification prompt
        rendered = service.get_classification_prompt(doc_types)

        # Then the bullet list should include each category.type, plus 'autre'
        for dt in doc_types:
            schema = _load_schema(dt)
            assert f"- {schema['type']}" in rendered
        assert "- autre" in rendered

        # And the distinctive characteristics section should include headers and each description item
        for dt in doc_types:
            schema = _load_schema(dt)
            header = f"**{schema['name']}** ({schema['type']})"
            assert header in rendered
            for item in schema.get("description", []):
                assert f"- {item}" in rendered

        # And the response format JSON keys should be present
        assert '"document_type"' in rendered
        assert '"confidence"' in rendered
        assert '"explanation"' in rendered


    def test_classification_prompt_is_cwd_independent(self, tmp_path, monkeypatch):
        # Change CWD to a temporary directory to ensure PromptService resolves paths relative to its file
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            service = PromptService()
            rendered = service.get_classification_prompt([SupportedDocumentType.CNI])
            # Minimal assertions: contains the CNI type and the response JSON keys
            cni_schema = _load_schema(SupportedDocumentType.CNI)
            assert f"- {cni_schema['type']}" in rendered
            assert '"document_type"' in rendered
            assert '"confidence"' in rendered
            assert '"explanation"' in rendered
        finally:
            os.chdir(old_cwd)


    def test_get_classification_prompt_raises_if_schema_missing(self, tmp_path):
        service = PromptService()
        # Point schemas_directory to an empty temp dir
        service.schemas_directory = tmp_path

        with pytest.raises(FileNotFoundError):
            service.get_classification_prompt([SupportedDocumentType.CNI])
