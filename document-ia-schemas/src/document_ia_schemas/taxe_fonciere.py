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
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    date_mise_en_recouvrement: FuzzyDate = Field(
        default=None,
        description="Date de mise en recouvrement de la taxe fonciere.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    identite_destinataire: list[Identity] = Field(
        default=list(),
        description="Identités des personnes physiques destinataires de l'avis figurant au-dessus de l'adresse sur la page 1.",
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        },
    )
    identites_proprietaires: list[Identity] = Field(
        default=list(),
        description="Identités des propriétaires imposés. Aller chercher les noms des personnes dans le tableau de la page 2 nommé DÉBITEUR(S) LÉGAL(AUX)",
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
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    reference_avis: Optional[str] = Field(
        default=None,
        description="Reference unique de l'avis de taxe fonciere.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    montant_taxe_fonciere: Optional[float] = Field(
        default=None,
        description="Montant de la taxe fonciere hors frais annexes en euros.",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class TaxeFonciereExtractSchema(BaseDocumentTypeSchema[TaxeFonciereModel]):
    type: str = "taxe_fonciere"
    name: str = "Taxe fonciere"
    description: list[str] = [
        "Document fiscal local relatif a la taxe fonciere sur les proprietes",
        "Contient une reference d'avis et une annee d'imposition",
        "Identifie les propriétaires imposés et le bien immobilier concerne",
        "Mentionne la base d'imposition et les montants a payer",
        "Peut contenir la date de mise en recouvrement",
    ]
    examples: list[TaxeFonciereModel] = [
        TaxeFonciereModel(
            annee_imposition="2025",
            date_mise_en_recouvrement=date(2025, 8, 31),
            identite_destinataire=["DUPONT Camille", "DUPONT Marie"],
            identites_proprietaires=["DUPONT Camille", "MARTIN Marie"],
            adresse_bien_impose="10 RUE DE LA PAIX 75001 PARIS",
            reference_avis="1234567890123",
            montant_taxe_fonciere=1185.0,
        ),
        TaxeFonciereModel(
            annee_imposition="2025",
            date_mise_en_recouvrement=date(2025, 9, 15),
            identite_destinataire=["MARTIN Nora", "DUPONT Alex"],
            identites_proprietaires=["MARTIN Nora", "DUPONT Alex"],
            adresse_bien_impose="22 AVENUE VICTOR HUGO 69003 LYON",
            reference_avis="12 34 5678912 34",
            montant_taxe_fonciere=930.0,
        ),
    ]

    document_model: Type[TaxeFonciereModel] = TaxeFonciereModel
