from datetime import date
from typing import List, Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
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
        "Doit obligatoirement contenir l'intégralité du certificat officiel Action Logement, même si le document comporte également des captures d'écran web/mobile ou des e-mails parasites en première page ou en pièce jointe.",
        "Présence du titre officiel ou équivalent : \"Certificat à remettre au bailleur pour la souscription d'un contrat Visale\" (ou \"Remettez ce certificat à votre bailleur...\").",
        "Contient impérativement la formule d'engagement : \"Action Logement certifie que le(s) candidat(s) mentionné(s) ci-dessous bénéficie (nt) de la garantie Visale\" ou \"ACTION LOGEMENT SE PORTE CAUTION\".",
        "Présence d'un numéro de visa unique (ex: Visa n°V123456789) accompagné des mentions \"attribué le\" et \"ce visa est valable jusqu'au\".",
        "Indique les plafonds de loyer mensuel charges comprises (ex: montant maximum en Île-de-France, etc.).",
        "Présence de la section d'instructions au bailleur (\"Bailleur, comment activer votre garantie\").",
        "EXCLUSION : Si le document contient UNIQUEMENT une capture d'écran de l'espace client (dashboard, statut \"en attente d'acceptation\", bouton \"ANNULER MON VISA\", etc.) ou un e-mail SANS que le texte du certificat officiel ne soit présent plus bas dans le texte de l'OCR, le classer en `autre`.",
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
