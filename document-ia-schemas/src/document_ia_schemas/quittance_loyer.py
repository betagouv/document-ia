from datetime import date
from enum import Enum
from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric
from document_ia_schemas.identity import Identity


class NatureDocumentQuittance(str, Enum):
    QUITTANCE = "quittance"
    RECU = "recu"
    AVIS_ECHEANCE = "avis_echeance"


class TypeParc(str, Enum):
    PRIVE = "prive"
    SOCIAL = "social"


class TypeBailleur(str, Enum):
    PARTICULIER = "particulier"
    PERSONNE_MORALE = "personne_morale"
    MANDATAIRE = "mandataire"


class LocataireModel(BaseModel):
    identite: Identity = Field(
        default=None,
        description="Nom et prénom du locataire",
        examples=["DUPONT Camille"],
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        }
    )


class BailleurModel(BaseModel):
    type_bailleur: Optional[TypeBailleur] = Field(
        default=None,
        description="Type de bailleur: particulier, personne morale ou mandataire.",
        examples=[TypeBailleur.MANDATAIRE.value],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    nom_raison_sociale: Optional[str] = Field(
        default=None,
        description="Nom du bailleur (personne physique) ou raison sociale.",
        examples=["CABINET GESTION HABITAT"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    siren_bailleur: Optional[str] = Field(
        default=None,
        description="SIREN du bailleur (9 chiffres) si le bailleur est immatricule.",
        examples=["123456789"],
        pattern=r"^\d{9}$",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    numero_carte_professionnelle: Optional[str] = Field(
        default=None,
        description="Numero de carte professionnelle (souvent prefixe par CPI) pour un mandataire.",
        examples=["CPI75012022000000001"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class QuittanceLoyerModel(BaseModel):
    nature_document: Optional[NatureDocumentQuittance] = Field(
        default=NatureDocumentQuittance.QUITTANCE,
        description="Nature du document immobilier (quittance, recu partiel, avis d'echeance).",
        examples=[NatureDocumentQuittance.QUITTANCE.value],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    type_parc: Optional[TypeParc] = Field(
        default=None,
        description="Type de parc locatif (prive ou social/HLM).",
        examples=[TypeParc.PRIVE.value],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    bailleur: Optional[BailleurModel] = Field(
        default=None,
        description="Informations d'identification du bailleur ou mandataire.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    locataires: list[LocataireModel] = Field(
        default_factory=list,
        description="Liste des locataires mentionnes sur la quittance.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    adresse_bien_loue: Optional[str] = Field(
        default=None,
        description="Adresse du logement loue.",
        examples=["12 rue des Lilas 75012 Paris"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    periode_debut: FuzzyDate = Field(
        default=None,
        description="Date de debut de la periode couverte.",
        examples=["2026-04-01"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    periode_fin: FuzzyDate = Field(
        default=None,
        description="Date de fin de la periode couverte.",
        examples=["2026-04-30"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    date_paiement: FuzzyDate = Field(
        default=None,
        description="Date de reception effective du paiement.",
        examples=["2026-05-05"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    date_emission: FuzzyDate = Field(
        default=None,
        description="Date d'emission de la quittance.",
        examples=["2026-05-05"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    loyer_de_base: Optional[float] = Field(
        default=None,
        description="Montant du loyer hors charges.",
        examples=[850.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    provisions_charges: Optional[float] = Field(
        default=None,
        description="Montant des provisions sur charges.",
        examples=[70.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    presence_signature: Optional[bool] = Field(
        default=None,
        description="Indique si une signature/cachet de validation est detectee.",
        examples=[True],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )


class QuittanceLoyerExtractSchema(BaseDocumentTypeSchema[QuittanceLoyerModel]):
    type: str = "quittance_loyer"
    name: str = "Quittance de loyer"
    description: list[str] = [
        "Document attestant le paiement du loyer et des charges pour une periode donnee",
        "Peut etre emis par un bailleur particulier, une personne morale ou une agence immobiliere",
        "Distingue le loyer hors charges, les provisions et le total acquitte",
        "Peut inclure des lignes specifiques: CAF/APL, regularisation, TEOM, SLS, indexation IRL",
        "La quittance est differente d'un recu partiel et d'un avis d'echeance",
    ]
    examples: list[QuittanceLoyerModel] = [
        QuittanceLoyerModel(
            nature_document=NatureDocumentQuittance.QUITTANCE,
            type_parc=TypeParc.PRIVE,
            bailleur=BailleurModel(
                type_bailleur=TypeBailleur.MANDATAIRE,
                nom_raison_sociale="CABINET GESTION HABITAT",
                numero_carte_professionnelle="CPI75012022000000001",
            ),
            locataires=[LocataireModel(identite="DUPONT Camille")],
            adresse_bien_loue="12 rue des Lilas 75012 Paris",
            periode_debut=date(2026, 4, 1),
            periode_fin=date(2026, 4, 30),
            date_paiement=date(2026, 5, 5),
            date_emission=date(2026, 5, 5),
            loyer_de_base=850.0,
            provisions_charges=70.0,
            presence_signature=True
        ),
        QuittanceLoyerModel(
            nature_document=NatureDocumentQuittance.QUITTANCE,
            type_parc=TypeParc.SOCIAL,
            bailleur=BailleurModel(type_bailleur=TypeBailleur.PERSONNE_MORALE, nom_raison_sociale="OFFICE HLM"),
            locataires=[LocataireModel(identite="MARTIN Nora")],
            periode_debut=date(2026, 1, 1),
            periode_fin=date(2026, 1, 31),
            loyer_de_base=500.0,
            provisions_charges=90.0,
        ),
    ]

    document_model: Type[QuittanceLoyerModel] = QuittanceLoyerModel
