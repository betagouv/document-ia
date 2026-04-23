from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric


class CNIModel(BaseModel):
    numero_document: Optional[str] = Field(
        default=None,
        description="Identifiant unique de la carte d'identité (format alphanumérique)",
        examples=["123456789012"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    date_delivrance: FuzzyDate = Field(
        description="Date d'émission du document (format JJ MM AAAA). Si absente, renseigner `null`.",
        examples=["2010-01-01"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_expiration: FuzzyDate = Field(
        description="Date limite de validité du document (format JJ MM AAAA). Une carte d'identité est valide 10 ans. Si absente renseigner `null`.",
        examples=["2020-01-01"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    nom: Optional[str] = Field(
        default=None,
        description="Nom de famille du titulaire (en majuscules sur le document)",
        examples=["DUPONT"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenom: Optional[str] = Field(
        default=None,
        description="Prénom du titulaire, uniquement le premier s'il y en a plusieurs",
        examples=["JEAN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_naissance: FuzzyDate = Field(
        description="Date de naissance du titulaire (format JJ MM AAAA). Si absente renseigner `null`.",
        examples=["1990-01-01"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Lieu de naissance du titulaire",
        examples=["PARIS 15e"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    nationalite: Optional[str] = Field(
        default=None,
        description="Nationalité du titulaire (en majuscules sur le document)",
        examples=["FRANÇAISE"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    bande_mrz: Optional[str] = Field(
        description="Bande Mrz de la carte d'identité (Machine Readable Zone). Si absent, renseigné `null`.",
        examples=[
            "IDFRADUPONT<<JEAN<ROBIN<ADRIEN<<<><><<<<<>>>123456789012FRA0002152F2809160<<<<<<<<<<<<<<00"
        ],
        default=None,
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )


class CNIExtractSchema(BaseDocumentTypeSchema[CNIModel]):
    type: str = "cni"
    name: str = "Carte nationale d'identité"
    description: list[str] = [
        "Document officiel français (carte nationale d'identité ou CNI)",
        'Contient des mentions comme "République Française"',
        "Présence d'informations : nom, prénom, date et lieu de naissance",
        "Numéro de carte à 12 chiffres",
        "Date de délivrance et date d'expiration",
        "Mention de l'autorité de délivrance (préfécture ou sous-préfécture)",
        "Peut contenir des codes MRZ (Machine Readable Zone) sous forme de lignes de caractères avec symboles <",
    ]
    examples: list[CNIModel] = [
        CNIModel(
            numero_document="123456789012",
            date_delivrance="2010-01-01",
            date_expiration="2020-01-01",
            nom="DUPONT",
            prenom="JEAN",
            date_naissance="1990-01-01",
            lieu_naissance="PARIS 15e",
            nationalite="FRANÇAISE",
            bande_mrz=(
                "IDFRADUPONT<<JEAN<ROBIN<ADRIEN<<<><><<<<<>>>123456789012FRA"
                "0002152F2809160<<<<<<<<<<<<<<00"
            ),
        )
    ]
    document_model: Type[CNIModel] = CNIModel
