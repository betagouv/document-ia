from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class PasseportModel(BaseModel):
    numero_document: str = Field(
        description="Identifiant unique / Numéro du passeport (format alphanumérique)",
        alias="Numéro du passeport",
        examples=["123456789012"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    nom: str = Field(
        description="Nom de famille du titulaire (en majuscules sur le document)",
        alias="Nom",
        examples=["DUPONT"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenom: str = Field(
        description="Prénom du titulaire (premier prénom)",
        alias="Prénom",
        examples=["JEAN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    lieu_naissance: str = Field(
        description="Lieu de naissance du titulaire (ville)",
        alias="Lieu de naissance",
        examples=["PARIS 15e"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    nationalite: str = Field(
        description="Nationalité du titulaire",
        alias="Nationalité",
        examples=["Française"], 
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    bande_mrz: str = Field(
        description="Bande MRZ du passeport",
        alias="Bande MRZ",
        examples=[
            "P<FRADUPONT<<JEAN<ROBIN<ADRIEN<<<><><<<<<>>>123456789012FRA0002152F2809160<<<<<<<<<<<<<<00"
        ],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_delivrance: Optional[str] = Field(
        default=None,
        description="Date d'émission du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'émission",
        examples=["01/01/2010"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_expiration: Optional[str] = Field(
        default=None,
        description="Date limite de validité du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'expiration",
        examples=["01/01/2020"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_naissance: Optional[str] = Field(
        default=None,
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de naissance",
        examples=["01/01/1990"],    
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
