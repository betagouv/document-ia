import pytest

from document_ia_schemas import SupportedDocumentType


def test_supported_document_type_from_str_accepts_other():
    assert SupportedDocumentType.from_str("autre") == SupportedDocumentType.AUTRE


def test_supported_document_type_from_str_accepts_quittance_loyer():
    assert (
        SupportedDocumentType.from_str("quittance_loyer")
        == SupportedDocumentType.QUITTANCE_LOYER
    )


def test_supported_document_type_from_str_accepts_attestation_hebergement():
    assert (
        SupportedDocumentType.from_str("attestation_hebergement")
        == SupportedDocumentType.ATTESTATION_HEBERGEMENT
    )


def test_supported_document_type_from_str_accepts_taxe_fonciere():
    assert (
        SupportedDocumentType.from_str("taxe_fonciere")
        == SupportedDocumentType.TAXE_FONCIERE
    )


def test_supported_document_type_from_str_still_rejects_unknown_value():
    with pytest.raises(ValueError):
        SupportedDocumentType.from_str("inconnu")
