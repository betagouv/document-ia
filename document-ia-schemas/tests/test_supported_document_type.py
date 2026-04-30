import pytest

from document_ia_schemas import SupportedDocumentType


def test_supported_document_type_from_str_accepts_other():
    assert SupportedDocumentType.from_str("autre") == SupportedDocumentType.AUTRE


def test_supported_document_type_from_str_accepts_quittance_loyer():
    assert (
        SupportedDocumentType.from_str("quittance_loyer")
        == SupportedDocumentType.QUITTANCE_LOYER
    )


def test_supported_document_type_from_str_still_rejects_unknown_value():
    with pytest.raises(ValueError):
        SupportedDocumentType.from_str("inconnu")
