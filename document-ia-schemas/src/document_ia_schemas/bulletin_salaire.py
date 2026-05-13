import re
from typing import Annotated, Any, Type, Optional

from pydantic import BaseModel, Field, BeforeValidator

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric

EMPLOYEE_TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:(?:m(?:onsieur)?|mme|madame|mlle|docteur|dr|prof(?:esseur)?|pr)\.?\s+)+",
    flags=re.IGNORECASE,
)


def normalize_employee_identity(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value

    normalized_value = value.replace(",", " ").strip()
    normalized_value = EMPLOYEE_TITLE_PREFIX_PATTERN.sub("", normalized_value)
    normalized_value = re.sub(r"\s+", " ", normalized_value).strip()
    return normalized_value or None


EmployeeIdentity = Annotated[Optional[str], BeforeValidator(normalize_employee_identity)]


class BulletinSalaireModel(BaseModel):
    # --- Identité Employeur ---
    nom_employeur: Optional[str] = Field(
        description="Nom ou raison sociale de l'employeur. Dans le texte, c'est généralement la **TOUTE PREMIÈRE personne ou entité** mentionnée au début du document. Si l'employeur est un particulier, son nom apparaîtra avant celui du salarié. Les informations de l'employeur sont souvent situées juste à côté du numéro SIRET ou du code NAF/APE.",
        default=None,
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )
    siret: Optional[str] = Field(
        description="Numéro SIRET de l'employeur (14 chiffres)",
        default=None,
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )

    # --- Identité Salarié ---
    identite_salarie: EmployeeIdentity = Field(
        default=None,
        description="Nom de famille et Prénoms du salarié. Dans la lecture du texte, il apparaît **APRÈS** l'employeur. Pour confirmer qu'il s'agit du salarié, cherche les éléments qui l'entourent souvent : son adresse personnelle, son numéro de Sécurité Sociale, son matricule, ou l'intitulé de son poste. Préférer le nom du salarié tel qu'il apparaît au niveau du destinataire du bulletin de salaire (ex: \"LAFONTAINE Patrice\" plutôt que \"LAFONTAINE Patrice née DUFOUR\").",
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        }
    )
    adresse_salarie: Optional[str] = Field(
        description="Adresse postale complète du salarié",
        default=None,
        json_schema_extra={
            "metrics": Metric.LEVENSHTEIN_DISTANCE
        }
    )

    # --- Détails du contrat ---
    periode_debut: FuzzyDate = Field(
        description="Date de début de la période de paie concernée (format JJ/MM/AAAA)",
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    periode_fin: FuzzyDate = Field(
        description="Date de fin de la période de paie concernée (format JJ/MM/AAAA)",
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_paiement: FuzzyDate = Field(
        description="Date de mise en paiement du salaire (format JJ/MM/AAAA)",
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    date_debut_contrat: FuzzyDate = Field(
        description="Date d'ancienneté ou d'entrée dans l'entreprise (format JJ/MM/AAAA), si absente, renseigner `null`.",
        default=None,
        json_schema_extra={
            "metrics": Metric.STRING_DATE_EQUALITY
        }
    )
    net_imposable: Optional[float] = Field(
        description="Montant du Net Imposable (base pour les impôts)",
        default=None,
        json_schema_extra={
            "metrics": Metric.COMPARE_NUMBER
        }
    )
    cumul_net_imposable: Optional[float] = Field(
        description="Cumul annuel du Net Imposable (souvent en bas de page), si absente, renseigner `null`.",
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
    examples: list[BulletinSalaireModel] = [
        BulletinSalaireModel(
            nom_employeur="ACME CORPORATION",
            siret="12345678900012",
            identite_salarie="MARTIN Thomas",
            adresse_salarie="10 RUE DE LA PAIX 75000 PARIS",
            periode_debut="2026-01-01",
            periode_fin="2026-01-31",
            date_paiement="2026-02-02",
            date_debut_contrat="2022-05-15",
            net_imposable=2800.00,
            cumul_net_imposable=32500.00,
        ),
        BulletinSalaireModel(
            nom_employeur="BOULANGERIE DUPONT",
            siret="12345678900012",
            identite_salarie="MARTIN Thomas",
            adresse_salarie="10 RUE DE LA PAIX 75000 PARIS",
            periode_debut="2026-01-01",
            periode_fin="2026-01-31",
            date_paiement="2026-02-02",
            date_debut_contrat="2022-05-15",
            net_imposable=2800.00,
            cumul_net_imposable=32500.00,
        ),
        BulletinSalaireModel(
            nom_employeur="Madame DURAND Valérie",
            siret="40536786300099",
            identite_salarie="LUCAS Bernard",
            adresse_salarie="12 CHEMIN DES ROSES 13000 MARSEILLE",
            periode_debut="2026-02-01",
            periode_fin="2026-02-28",
            date_paiement="2026-03-02",
            date_debut_contrat="2023-09-01",
            net_imposable=1850.50,
            cumul_net_imposable=3701.00
        )
    ]
    document_model: Type[BulletinSalaireModel] = BulletinSalaireModel
