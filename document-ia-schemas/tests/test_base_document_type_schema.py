import pytest

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.avis_imposition import AvisImpositionModel
from document_ia_schemas.bulletin_salaire import BulletinSalaireModel


class DummyAvisImpositionSchema(BaseDocumentTypeSchema[AvisImpositionModel]):
    document_model: type[AvisImpositionModel] = AvisImpositionModel


class DummyBulletinSalaireSchema(BaseDocumentTypeSchema[BulletinSalaireModel]):
    document_model: type[BulletinSalaireModel] = BulletinSalaireModel


def test_base_document_type_schema_accepts_homogeneous_examples():
    payload = DummyAvisImpositionSchema(
        examples=[
            AvisImpositionModel(annee_revenus="2023"),
            AvisImpositionModel(annee_revenus="2022"),
        ]
    )

    assert len(payload.examples) == 2
    assert all(isinstance(example, AvisImpositionModel) for example in payload.examples)


def test_base_document_type_schema_builds_typed_items_from_dicts():
    payload = DummyBulletinSalaireSchema(
        examples=[
            {"nom_employeur": "ACME CORPORATION"},
            {"nom_employeur": "BOULANGERIE DUPONT"},
        ]
    )

    assert [example.nom_employeur for example in payload.examples] == [
        "ACME CORPORATION",
        "BOULANGERIE DUPONT",
    ]


def test_base_document_type_schema_raises_when_instances_have_mixed_types():
    with pytest.raises(ValueError):
        DummyAvisImpositionSchema(
            examples=[
                AvisImpositionModel(annee_revenus="2023"),
                BulletinSalaireModel(nom_employeur="ACME CORPORATION"),
            ]
        )
