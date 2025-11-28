from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric

class PermisConduireModel(BaseModel):
    numero_document: str = Field(
        description="Identifiant unique du permis de conduire (format alphanumérique).",
        alias="Numéro du permis",
        examples=["1234567890123456789"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    date_delivrance: str = Field(
        description="Date de délivrance du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de délivrance",
        examples=["15/06/2010"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_expiration: str = Field(
        description="Date limite de validité du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'expiration",
        examples=["15/06/2030"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    nom: str = Field(
        description="Nom de famille du titulaire (en majuscules sur le document).",
        alias="Nom",
        examples=["DUPONT"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenom: str = Field(
        description="Prénom du titulaire (premier prénom).",
        alias="Prénom",
        examples=["JEAN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_naissance: str = Field(
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de naissance",
        examples=["01/01/1990"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Lieu de naissance du titulaire (ville). Si absente, renseigner `null`.",
        alias="Lieu de naissance",
        examples=["PARIS"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    adresse: Optional[str] = Field(
        default=None,
        description="Adresse de résidence du titulaire. Si absente, renseigner `null`.",
        alias="Adresse",
        examples=["123 Rue de la Paix, 75008 Paris"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
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
