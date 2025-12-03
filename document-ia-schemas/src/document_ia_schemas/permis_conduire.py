from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate


class PermisConduireModel(BaseModel):
    numero_document: str = Field(
        description="Identifiant unique du permis de conduire (format alphanumérique).",
        alias="Numéro du permis",
        examples=["1234567890123456789"],
    )
    date_delivrance: FuzzyDate = Field(
        description="Date de délivrance du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de délivrance",
        examples=["2010-06-15"],
    )
    date_expiration: FuzzyDate = Field(
        description="Date limite de validité du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'expiration",
        examples=["2030-06-15"],
    )
    nom: str = Field(
        description="Nom de famille du titulaire (en majuscules sur le document).",
        alias="Nom",
        examples=["DUPONT"],
    )
    prenom: str = Field(
        description="Prénom du titulaire (premier prénom).",
        alias="Prénom",
        examples=["JEAN"],
    )
    date_naissance: FuzzyDate = Field(
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de naissance",
        examples=["1990-01-01"],
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Lieu de naissance du titulaire (ville). Si absente, renseigner `null`.",
        alias="Lieu de naissance",
        examples=["PARIS"],
    )
    adresse: Optional[str] = Field(
        default=None,
        description="Adresse de résidence du titulaire. Si absente, renseigner `null`.",
        alias="Adresse",
        examples=["123 Rue de la Paix, 75008 Paris"],
    )


class PermisConduireExtractSchema(BaseDocumentTypeSchema[PermisConduireModel]):
    type: str = "permis_conduire"
    name: str = "Permis de conduire"
    description: list[str] = [
        "Document officiel permettant de conduire un véhicule sur la voie publique",
        'Format carte avec mentions "Permis de conduire" ou "Driving licence"',
        'Contient des mentions comme "République Française" ou "Union Européenne"',
        "Catégories de permis (A, B, etc.)",
        "Numéro de permis à 12 chiffres",
        "Présence d'informations : nom, prénom, date et lieu de naissance, adresse, numéro de permis",
        "Dates de délivrance et d'expiration pour chaque catégorie",
        "Photo d'identité du titulaire, signature et éventuellement une puce électronique",
    ]

    document_model: Type[PermisConduireModel] = PermisConduireModel
