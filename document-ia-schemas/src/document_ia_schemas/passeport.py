from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric


class PasseportModel(BaseModel):
    numero_document: Optional[str] = Field(
        default=None,
        description="Identifiant unique / Numéro du passeport (format alphanumérique)",
        alias="Numéro du passeport",
        examples=["123456789012"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    nom: Optional[str] = Field(
        default=None,
        description="Nom de famille du titulaire (en majuscules sur le document)",
        alias="Nom",
        examples=["DUPONT"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenom: Optional[str] = Field(
        default=None,
        description="Prénom du titulaire (premier prénom)",
        alias="Prénom",
        examples=["JEAN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Lieu de naissance du titulaire (ville)",
        alias="Lieu de naissance",
        examples=["PARIS 15e"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    nationalite: Optional[str] = Field(
        default=None,
        description="Nationalité du titulaire",
        alias="Nationalité",
        examples=["Française"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    bande_mrz: Optional[str] = Field(
        default=None,
        description="Bande MRZ du passeport",
        alias="Bande MRZ",
        examples=[
            "P<FRADUPONT<<JEAN<ROBIN<ADRIEN<<<><><<<<<>>>123456789012FRA0002152F2809160<<<<<<<<<<<<<<00"
        ],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_delivrance: FuzzyDate = Field(
        default=None,
        description="Date d'émission du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'émission",
        examples=["2010-01-01"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_expiration: FuzzyDate = Field(
        default=None,
        description="Date limite de validité du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'expiration",
        examples=["2020-01-01"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_naissance: FuzzyDate = Field(
        default=None,
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de naissance",
        examples=["1990-01-01"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )


class PasseportExtractSchema(BaseDocumentTypeSchema[PasseportModel]):
    type: str = "passeport"
    name: str = "Passeport"
    description: list[str] = [
        "Document de voyage international",
        'Mentions "Passeport", "Passport" ou "Union Européenne"',
        "Numéro de passeport (généralement alphanumériques)",
        "Présence d'informations : nom, prénom, date et lieu de naissance, nationalité",
        "Dates de délivrance et d'expiration",
        "Peut contenir des codes MRZ (Machine Readable Zone) sous forme de lignes de caractères avec symboles <",
    ]
    document_model: Type[PasseportModel] = PasseportModel
