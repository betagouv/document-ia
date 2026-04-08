import os

import pytest

from document_ia_schemas.cni import CNIModel
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.exception.unsupported_document_type import UnsupportedDocumentType


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

        # Then the bullet list should include each category.type, plus only one category 'autre' (AUTRE)
        for dt in doc_types:
            schema = service._get_schema_class_instance(dt)
            assert f"- {schema.type}" in rendered
        # Category 'autre' (AUTRE) only once
        assert rendered.count("- autre") == 1

        # And the distinctive characteristics section should include headers and each description item
        for dt in doc_types:
            schema = service._get_schema_class_instance(dt)
            header = f"**{schema.name}** ({schema.type})"
            assert header in rendered
            for item in schema.description:
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
            cni_schema = service._get_schema_class_instance(SupportedDocumentType.CNI)
            assert f"- {cni_schema.type}" in rendered
            assert '"document_type"' in rendered
            assert '"confidence"' in rendered
            assert '"explanation"' in rendered
        finally:
            os.chdir(old_cwd)

    def test_get_classification_prompt_raises_if_schema_missing(self, tmp_path):
        service = PromptService()

        # Instead of swapping a schemas_directory (no longer used), request a document type
        # for which no schema exists. We pass a lightweight object with a .value attribute.
        class FakeDocType:
            value = "this_schema_does_not_exist"

        with pytest.raises(UnsupportedDocumentType):
            service.get_classification_prompt([FakeDocType()])

    def test_get_extraction_prompt_returns_schema_and_model_for_cni(self):
        """Ensure get_extraction_prompt('cni') returns the schema content and the CNIExtract model class."""
        service = PromptService()

        prompt_text, model_class = service.get_extraction_prompt(SupportedDocumentType.CNI)

        # The model class should be the CNIExtract defined in the cni model module

        assert model_class is CNIModel

        schema_instance = service._get_schema_class_instance(SupportedDocumentType.CNI)

        # The template should have been rendered with the document name
        assert schema_instance.name in prompt_text

        # And each description item should appear in the prompt
        for desc in schema_instance.description:
            assert desc in prompt_text

        # The prompt should embed the explicit schema examples
        for key, value in schema_instance.examples[0].model_dump(mode="json").items():
            assert f'"{key}"' in prompt_text

        # The template iterates document_json_properties: ensure keys and property descriptions are present
        for key, prop in schema_instance.get_json_schema_dict().get("properties", {}).items():
            assert key in prompt_text
            if isinstance(prop, dict) and prop.get("description"):
                assert prop.get("description") in prompt_text

    def test_get_extraction_prompt_raises_for_unknown_document(self):
        """Requesting a prompt for an unknown document type should raise UnsupportedDocumentType."""
        service = PromptService()
        with pytest.raises(UnsupportedDocumentType):
            service.get_extraction_prompt("type_inconnu")

    def test_classification_prompt_restricts_to_provided_document_types(self):
        """Only the provided document types should appear in the rendered prompt."""
        service = PromptService()

        restricted_types = [SupportedDocumentType.CNI, SupportedDocumentType.PASSEPORT]
        excluded_types = [
            SupportedDocumentType.PERMIS_CONDUIRE,
            SupportedDocumentType.AVIS_IMPOSITION,
            SupportedDocumentType.BULLETIN_SALAIRE,
            SupportedDocumentType.VISALE,
        ]

        rendered = service.get_classification_prompt(restricted_types)

        for dt in restricted_types:
            schema = service._get_schema_class_instance(dt)
            assert f"- {schema.type}" in rendered

        for dt in excluded_types:
            schema = service._get_schema_class_instance(dt)
            assert f"- {schema.type}" not in rendered
