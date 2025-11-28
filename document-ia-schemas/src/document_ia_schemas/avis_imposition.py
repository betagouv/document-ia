from typing import Optional, Type
from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class AvisImpositionModel(BaseModel):
    annee_revenus: str = Field(
        description="Année fiscale concernée par la déclaration de revenus (format AAAA)",
        alias="Année des revenus",
        examples=["2023"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    date_mise_en_recouvrement: Optional[str] = Field(
        default=None,
        description=(
            "Date de mise en recouvrement de l'impôt (format JJ/MM/AAAA). Si absente, renseigner `null`."
        ),
        alias="Date de mise en recouvrement",
        examples=["31/07/2024"],
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    declarant_1_identite: str = Field(
        description="Nom et prénom du premier déclarant tel qu'il apparait au niveau du destinataire",
        alias="Nom et Prénom du déclarant 1",
        examples=["MARTIN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    declarant_1_nom_naissance: str = Field(
        description="Nom de naissance du premier déclarant, il peut être différent du nom et prénom du déclarant 1",
        alias="Nom de naissance du déclarant 1",
        examples=["MARTIN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    # declarant_1_prenom: Optional[str] = Field(
    #     default=None,
    #     description="Prénom du premier déclarant",
    #     alias="Prénom du déclarant 1",
    #     examples=["SOPHIE"],
    # )
    declarant_1_numero_fiscal: Optional[str] = Field(
        default=None,
        description="Numéro fiscal personnel du premier déclarant (13 chiffres)",
        alias="Numéro fiscal du déclarant 1",
        examples=["1234567890123"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }

    )
    declarant_2_identite: str = Field(
        description="Nom et prénom du deuxième déclarant tel qu'il apparait au niveau du destinataire",
        alias="Nom et Prénom du déclarant 2",
        examples=["MARTIN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    declarant_2_nom_naissance: str = Field(
        description="Nom de naissance du deuxième déclarant, il peut être différent du nom et prénom du déclarant 2",
        alias="Nom de naissance du déclarant 2",
        examples=["MARTIN"],
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    # declarant_2_prenom: Optional[str] = Field(
    #     default=None,
    #     description="Prénom du deuxième déclarant",
    #     alias="Prénom du déclarant 2",
    #     examples=["SOPHIE"],
    # )
    declarant_2_numero_fiscal: Optional[str] = Field(
        default=None,
        description="Numéro fiscal personnel du deuxième déclarant (13 chiffres)",
        alias="Numéro fiscal du déclarant 2",
        examples=["1234567890123"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    reference_avis: Optional[str] = Field(
        default=None,
        description=(
            "Référence unique de l'avis d'imposition (format numérique, généralement 13 ou 14 chiffres). Information présente juste après les numéros fiscaux des déclarants."
        ),
        alias="Référence d'avis d'impôt",
        examples=["1234567890123"],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    nombre_parts: Optional[float] = Field(
        default=None,
        description="Nombre de parts fiscales du foyer (peut être décimal)",
        alias="Nombre de parts",
        examples=[2.5],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }

    )
    revenu_fiscal_reference: float = Field(
        description="Revenu fiscal de référence (RFR) du foyer en euros",
        alias="Revenu fiscal de référence",
        examples=[45000],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    revenu_brut_global: Optional[float] = Field(
        default=None,
        description="Revenu brut global du foyer en euros.",
        alias="Revenu brut global",
        examples=[50000],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    revenu_imposable: Optional[float] = Field(
        default=None,
        description="Revenu net imposable du foyer en euros.",
        alias="Revenu imposable",
        examples=[42000],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    impot_revenu_net_avant_corrections: Optional[float] = Field(
        default=None,
        description="Montant de l'impôt sur le revenu net avant corrections en euros.",
        alias="Impôt sur le revenu net avant corrections",
        examples=[5500],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    montant_impot: Optional[float] = Field(
        default=None,
        description=(
            "Montant total de l'impôt à payer ou remboursement en euros (peut être négatif)."
        ),
        alias="Montant de l'impôt",
        examples=[5000],
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )


class AvisImpositionExtractSchema(BaseDocumentTypeSchema[AvisImpositionModel]):
    type: str = "avis_imposition"
    name: str = "Avis d'imposition"
    description: list[str] = [
        "Document officiel français émis par la Direction Générale des Finances Publiques (DGFiP)",
        'Contient des mentions comme "Impôts.gouv.fr" ou "Direction Générale des Finances Publiques"',
        "Présence d'informations fiscales : revenus, impôts, nombre de parts",
        "Référence d'avis unique (numéro à 13 ou 14 chiffres)",
        "Identifie le ou les déclarants (nom, prénom, numéro fiscal)",
        "Indique l'année des revenus déclarés",
        "Mentionne le revenu fiscal de référence (RFR)",
        "Date de mise en recouvrement de l'impôt",
        "Peut contenir un QR code pour vérification en ligne",
    ]

    document_model: Type[AvisImpositionModel] = AvisImpositionModel
