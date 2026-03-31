import pytest

from document_ia_schemas import SupportedDocumentType


def test_supported_document_type_from_str_accepts_other():
    assert SupportedDocumentType.from_str("autre") == SupportedDocumentType.OTHER


def test_supported_document_type_from_str_still_rejects_unknown_value():
    with pytest.raises(ValueError):
        SupportedDocumentType.from_str("inconnu")
