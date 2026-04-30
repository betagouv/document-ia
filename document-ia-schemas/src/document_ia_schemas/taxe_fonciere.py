from datetime import date
from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric
from document_ia_schemas.identity import Identity


class TaxeFonciereModel(BaseModel):
    annee_imposition: Optional[str] = Field(
        default=None,
        description="Annee d'imposition de la taxe fonciere (format AAAA).",
        examples=["2025"],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    date_mise_en_recouvrement: FuzzyDate = Field(
        default=None,
        description="Date de mise en recouvrement de la taxe fonciere.",
        examples=["2025-08-31"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    proprietaire_identite: Identity = Field(
        default=None,
        description="Identite du proprietaire impose.",
        examples=["DUPONT Camille"],
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        },
    )
    adresse_bien_impose: Optional[str] = Field(
        default=None,
        description="Adresse du bien immobilier concerne par la taxe fonciere.",
        examples=["10 RUE DE LA PAIX 75001 PARIS"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    reference_avis: Optional[str] = Field(
        default=None,
        description="Reference unique de l'avis de taxe fonciere.",
        examples=["1234567890123", "12 34 5678912 34"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    base_nette_imposition: Optional[float] = Field(
        default=None,
        description="Base nette d'imposition en euros.",
        examples=[2487.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    montant_taxe_fonciere: Optional[float] = Field(
        default=None,
        description="Montant de la taxe fonciere hors frais annexes en euros.",
        examples=[1185.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    montant_total_a_payer: Optional[float] = Field(
        default=None,
        description="Montant total a payer de la taxe fonciere en euros.",
        examples=[1240.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class TaxeFonciereExtractSchema(BaseDocumentTypeSchema[TaxeFonciereModel]):
    type: str = "taxe_fonciere"
    name: str = "Taxe fonciere"
    description: list[str] = [
        "Document fiscal local relatif a la taxe fonciere sur les proprietes",
        "Contient une reference d'avis et une annee d'imposition",
        "Identifie le proprietaire impose et le bien immobilier concerne",
        "Mentionne la base d'imposition et les montants a payer",
        "Peut contenir la date de mise en recouvrement",
    ]
    examples: list[TaxeFonciereModel] = [
        TaxeFonciereModel(
            annee_imposition="2025",
            date_mise_en_recouvrement=date(2025, 8, 31),
            proprietaire_identite="DUPONT Camille",
            adresse_bien_impose="10 RUE DE LA PAIX 75001 PARIS",
            reference_avis="1234567890123",
            base_nette_imposition=2487.0,
            montant_taxe_fonciere=1185.0,
            montant_total_a_payer=1240.0,
        ),
        TaxeFonciereModel(
            annee_imposition="2025",
            date_mise_en_recouvrement=date(2025, 9, 15),
            proprietaire_identite="MARTIN Nora",
            adresse_bien_impose="22 AVENUE VICTOR HUGO 69003 LYON",
            reference_avis="12 34 5678912 34",
            base_nette_imposition=1998.0,
            montant_taxe_fonciere=930.0,
            montant_total_a_payer=972.5,
        ),
    ]

    document_model: Type[TaxeFonciereModel] = TaxeFonciereModel
