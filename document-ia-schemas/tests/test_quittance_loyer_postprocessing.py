import pytest

from document_ia_schemas.quittance_loyer import LocataireModel


@pytest.mark.parametrize(
	("raw_identity", "expected_identity"),
	[
		("M. MARTIN Thomas", "MARTIN Thomas"),
		("Mme, DUPONT Jeanne", "DUPONT Jeanne"),
		("Dr.  LAFONTAINE, Patrice", "LAFONTAINE Patrice"),
	],
)
def test_locataire_identity_postprocessing_removes_titles_and_commas(
	raw_identity: str, expected_identity: str
):
	model = LocataireModel(identite=raw_identity)

	assert model.identite == expected_identity
