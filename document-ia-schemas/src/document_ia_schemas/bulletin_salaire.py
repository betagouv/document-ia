from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate

from document_ia_schemas.field_metrics import Metric

class BulletinSalaireModel(BaseModel):
    # --- Identité Employeur ---
    nom_employeur: Optional[str] = Field(
        description="Nom ou raison sociale de l'employeur",
        alias="Employeur",
        examples=["ACME CORPORATION", "BOULANGERIE DUPONT"],
        default=None,
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    siret: Optional[str] = Field(
        description="Numéro SIRET de l'employeur (14 chiffres)",
        alias="SIRET Employeur",
        examples=["12345678900012"],
        default=None,
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )

    # --- Identité Salarié ---
    identite_salarie: Optional[str] = Field(
        default=None,
        description="Nom de famille et Prénoms du salarié",
        alias="Nom et Prénoms du salarié",
        examples=["MARTIN Thomas"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    adresse_salarie: Optional[str] = Field(
        description="Adresse postale complète du salarié",
        alias="Adresse du salarié",
        examples=["10 RUE DE LA PAIX 75000 PARIS"],
        default=None,
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )

    # --- Détails du contrat ---
    periode_debut: FuzzyDate = Field(
        description="Date de début de la période de paie concernée (format JJ/MM/AAAA)",
        alias="Période début",
        examples=["2024-01-01"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    periode_fin: FuzzyDate = Field(
        description="Date de fin de la période de paie concernée (format JJ/MM/AAAA)",
        alias="Période fin",
        examples=["2024-01-31"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_paiement: FuzzyDate = Field(
        description="Date de mise en paiement du salaire (format JJ/MM/AAAA)",
        alias="Date de paiement",
        examples=["2024-02-02"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_debut_contrat: FuzzyDate = Field(
        description="Date d'ancienneté ou d'entrée dans l'entreprise (format JJ/MM/AAAA), si absente, renseigner `null`.",
        alias="Date de début de contrat",
        examples=["2018-05-15"],
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    net_imposable: Optional[float] = Field(
        description="Montant du Net Imposable (base pour les impôts)",
        alias="Net Imposable",
        examples=[2800.00],
        default=None,
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    cumul_net_imposable: Optional[float] = Field(
        description="Cumul annuel du Net Imposable (souvent en bas de page), si absente, renseigner `null`.",
        alias="Cumul Imposable Annuel",
        examples=["32500.00"],
        default=None,
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )


class BulletinSalaireExtractSchema(BaseDocumentTypeSchema[BulletinSalaireModel]):
    type: str = "bulletin_salaire"
    name: str = "Bulletin de salaire"
    description: list[str] = [
        "Document officiel de paie (Fiche de paie / Bulletin de salaire)",
        "Contient des mentions comme 'Bulletin de paie', 'Salaire', 'Employeur', 'Salarié'",
        "Présence d'un tableau avec des colonnes (libellé, base, taux, montant)",
        "Contient des montants Brut, Net Imposable et Net à Payer",
        "Mentionne souvent l'URSSAF, la CSG, la CRDS",
    ]
    document_model: Type[BulletinSalaireModel] = BulletinSalaireModel
