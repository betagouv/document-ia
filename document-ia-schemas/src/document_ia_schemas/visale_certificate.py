from datetime import date
from typing import List, Optional, Type

from document_ia_schemas.base_document_type_schema import FuzzyDate
from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class BeneficiaireModel(BaseModel):
    nom: Optional[str] = Field(
        default=None,
        description="Nom de famille du bénéficiaire / locataire",
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    prenoms: Optional[str] = Field(
        default=None,
        description="Prénoms du bénéficiaire / locataire",
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )


class VisaleModel(BaseModel):
    numero_visa: Optional[str] = Field(
        default=None,
        description="Numéro unique du visa Visale (commence généralement par la lettre V suivie de chiffres)",
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    date_delivrance: FuzzyDate = Field(
        default=None,
        description="Date d'attribution ou de délivrance du visa (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_fin_validite: FuzzyDate = Field(
        default=None,
        description="Date limite jusqu'à laquelle le visa est valable pour la signature du bail (format JJ/MM/AAAA).",
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    beneficiaires: List[BeneficiaireModel] = Field(
        description="Liste des candidats locataires (bénéficiaires) mentionnés sur le certificat. Lorsque plusieurs locataires sont couverts par la même garantie VISALE, leurs différentes identités sont déclinées (Prénom 1, Nom 1)",
    )


class VisaleExtractSchema(BaseDocumentTypeSchema[VisaleModel]):
    type: str = "visale_certificate"
    name: str = "Certificat de garantie Visale"
    description: list[str] = [
        "Certificat de garantie de loyers émis par Action Logement",
        "Contient un numéro de visa unique commençant par la lettre V",
        "Indique une date d'attribution et une date de fin de validité pour la signature du bail",
        "Mentionne l'identité complète des candidats locataires certifiés sous forme de liste numérotée",
        "Cette garantie peut couvrir un ou plusieurs candidats locataires"
    ]
    examples: list[VisaleModel] = [
        VisaleModel(
            numero_visa="V11706816406",
            date_delivrance=date(2026, 3, 2),
            date_fin_validite=date(2026, 5, 31),
            beneficiaires=[BeneficiaireModel(nom="DUPONT", prenoms="Grégoire")],
        ),
        VisaleModel(
            numero_visa="V11706816406",
            date_delivrance=date(2026, 3, 2),
            date_fin_validite=date(2026, 5, 31),
            beneficiaires=[BeneficiaireModel(nom="DE LACROIX", prenoms="Sophie-marie")],
        ),
        VisaleModel(
            numero_visa="V11706816406",
            date_delivrance=date(2026, 3, 2),
            date_fin_validite=date(2026, 5, 31),
            beneficiaires=[BeneficiaireModel(nom="Rouzet", prenoms="Jean Michel")],
        ),
    ]

    document_model: Type[VisaleModel] = VisaleModel
