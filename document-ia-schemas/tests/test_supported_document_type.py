import pytest

from document_ia_schemas import SupportedDocumentType


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("autre", SupportedDocumentType.AUTRE),
        ("quittance_loyer", SupportedDocumentType.QUITTANCE_LOYER),
        ("attestation_hebergement", SupportedDocumentType.ATTESTATION_HEBERGEMENT),
        ("taxe_fonciere", SupportedDocumentType.TAXE_FONCIERE),
    ],
)
def test_supported_document_type_from_str_accepts_known_values(raw_value, expected):
    assert SupportedDocumentType.from_str(raw_value) == expected
