import pytest

from document_ia_schemas.bulletin_salaire import BulletinSalaireModel


@pytest.mark.parametrize(
    ("raw_identity", "expected_identity"),
    [
        ("M. MARTIN Thomas", "MARTIN Thomas"),
        ("Mme, DUPONT Jeanne", "DUPONT Jeanne"),
        ("Docteur DURAND Alice", "DURAND Alice"),
        ("Dr.  LAFONTAINE, Patrice", "LAFONTAINE Patrice"),
        ("MARTIN Thomas", "MARTIN Thomas"),
    ],
)
def test_identite_salarie_postprocessing_removes_titles_and_commas(
    raw_identity: str, expected_identity: str
):
    # Given
    extracted_payload = {"identite_salarie": raw_identity}

    # When
    model = BulletinSalaireModel(**extracted_payload)

    # Then
    assert model.identite_salarie == expected_identity
