from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema  
from document_ia_schemas.field_metrics import Metric


class CNIModel(BaseModel):
    numero_document: str = Field(
        description="Identifiant unique de la carte d'identité (format alphanumérique)",
        alias="Numero de la carte d'identité",
        examples=["123456789012"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    date_delivrance: Optional[str] = Field(
        description="Date d'émission du document (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date d'émission",
        examples=["01/01/2010"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_expiration: Optional[str] = Field(
        description="Date limite de validité du document (format JJ/MM/AAAA). Une carte d'identité est valide 10 ans. Si absente renseigner `null`.",
        alias="Date d'expiration",
        examples=["01/01/2020"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    nom: str = Field(
        description="Nom de famille du titulaire (en majuscules sur le document",
        alias="Nom",
        examples=["DUPONT"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenom: str = Field(
        description="Prénom du titulaire, uniquement le premier s'il y en a plusieurs",
        alias="Prénom",
        examples=["JEAN"],  
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_naissance: Optional[str] = Field(
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente renseigner `null`.",
        alias="Date de naissance",
        examples=["01/01/1990"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    lieu_naissance: str = Field(
        description="Lieu de naissance du titulaire",
        alias="Lieu de naissance",
        examples=["PARIS 15e"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    nationalite: str = Field(
        description="Nationalité du titulaire (en majuscules sur le document)",
        alias="Nationalité",
        examples=["FRANÇAISE"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    bande_mrz: Optional[str] = Field(
        description="Bande Mrz de la carte d'identité (Machine Readable Zone). Si absent, renseigné `null`.",
        alias="Bande MRZ",
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
    document_model: Type[CNIModel] = CNIModel
