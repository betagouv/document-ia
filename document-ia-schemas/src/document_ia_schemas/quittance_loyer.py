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
            "metrics": Metric.SKIP  # Metric.LEVENSHTEIN_DISTANCE
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


class LigneFacturationModel(BaseModel):
    libelle: Optional[str] = Field(
        default=None,
        description="Libelle de ligne de facturation (loyer, charges, TEOM, regularisation, etc.).",
        examples=["Provision pour charges"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    montant: Optional[float] = Field(
        default=None,
        description="Montant de la ligne (peut etre negatif pour un avoir).",
        examples=[50.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class IndexationIrlModel(BaseModel):
    ancien_loyer: Optional[float] = Field(
        default=None,
        description="Montant du loyer avant reindexation IRL.",
        examples=[780.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    trimestre_reference_irl: Optional[str] = Field(
        default=None,
        description="Trimestre/periode de reference IRL (ex: T4 2024).",
        examples=["T4 2024"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    valeur_indice_ancien: Optional[float] = Field(
        default=None,
        description="Valeur IRL de reference precedente.",
        examples=[138.12],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    valeur_indice_nouveau: Optional[float] = Field(
        default=None,
        description="Nouvelle valeur IRL appliquee.",
        examples=[140.59],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class HlmSpecificsModel(BaseModel):
    montant_sls: Optional[float] = Field(
        default=None,
        description="Montant du supplement de loyer de solidarite (SLS).",
        examples=[120.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    coefficient_cdpr: Optional[float] = Field(
        default=None,
        description="Coefficient de depassement des plafonds de ressources (CDPR).",
        examples=[0.8],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    revenu_fiscal_retenu: Optional[float] = Field(
        default=None,
        description="Revenu fiscal retenu pour le calcul HLM/SLS.",
        examples=[42000.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class QuittanceLoyerModel(BaseModel):
    nature_document: Optional[NatureDocumentQuittance] = Field(
        default=NatureDocumentQuittance.QUITTANCE,
        description="Nature du document immobilier (quittance, recu partiel, avis d'echeance).",
        examples=[NatureDocumentQuittance.QUITTANCE.value],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    est_paiement_partiel: Optional[bool] = Field(
        default=None,
        description="Indique si le document correspond a un paiement partiel (recu).",
        examples=[False],
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
    tiers_payant_caf: Optional[float] = Field(
        default=None,
        description="Montant verse directement par un organisme tiers (CAF/APL).",
        examples=[120.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    organisme_tiers_payant: Optional[str] = Field(
        default=None,
        description="Nom de l'organisme tiers payant (ex: CAF).",
        examples=["CAF"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    regularisation_charges: Optional[float] = Field(
        default=None,
        description="Regularisation ponctuelle de charges (positive ou negative).",
        examples=[-25.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    montant_teom: Optional[float] = Field(
        default=None,
        description="Montant de TEOM facture au locataire le cas echeant.",
        examples=[15.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    prime_assurance_recuperable: Optional[float] = Field(
        default=None,
        description="Prime d'assurance recuperable (assurance pour compte du locataire).",
        examples=[8.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    frais_quittance: Optional[float] = Field(
        default=None,
        description="Frais de quittance identifies (devrait etre nul selon la reglementation).",
        examples=[0.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    montant_total_acquitte: Optional[float] = Field(
        default=None,
        description="Montant total acquitte pour la periode.",
        examples=[800.0],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )

    lignes_facturation: list[LigneFacturationModel] = Field(
        default_factory=list,
        description="Lignes de facturation detaillees presentes sur le document.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    indexation_irl: Optional[IndexationIrlModel] = Field(
        default=None,
        description="Bloc de donnees d'indexation IRL lorsqu'il est present.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    hlm_specifics: Optional[HlmSpecificsModel] = Field(
        default=None,
        description="Bloc de donnees specifique au parc social/HLM.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )

    reference_mandat: Optional[str] = Field(
        default=None,
        description="Reference interne de mandat de gestion.",
        examples=["MAND-2026-00124"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    reference_locataire: Optional[str] = Field(
        default=None,
        description="Reference interne locataire/dossier.",
        examples=["LOC-88712"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    methode_paiement: Optional[str] = Field(
        default=None,
        description="Mode de paiement identifie (virement, cheque, prelevement).",
        examples=["virement"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
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
            est_paiement_partiel=False,
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
            tiers_payant_caf=120.0,
            organisme_tiers_payant="CAF",
            montant_total_acquitte=800.0,
            presence_signature=True,
            lignes_facturation=[
                LigneFacturationModel(libelle="Loyer de base", montant=850.0),
                LigneFacturationModel(libelle="Provision pour charges", montant=70.0),
                LigneFacturationModel(libelle="APL tiers payant", montant=-120.0),
            ],
        ),
        QuittanceLoyerModel(
            nature_document=NatureDocumentQuittance.QUITTANCE,
            est_paiement_partiel=False,
            type_parc=TypeParc.SOCIAL,
            bailleur=BailleurModel(type_bailleur=TypeBailleur.PERSONNE_MORALE, nom_raison_sociale="OFFICE HLM"),
            locataires=[LocataireModel(identite="MARTIN Nora")],
            periode_debut=date(2026, 1, 1),
            periode_fin=date(2026, 1, 31),
            loyer_de_base=500.0,
            provisions_charges=90.0,
            montant_total_acquitte=590.0,
            hlm_specifics=HlmSpecificsModel(
                montant_sls=120.0,
                coefficient_cdpr=0.8,
                revenu_fiscal_retenu=42000.0,
            ),
            indexation_irl=IndexationIrlModel(
                ancien_loyer=490.0,
                trimestre_reference_irl="T4 2024",
                valeur_indice_ancien=138.12,
                valeur_indice_nouveau=140.59,
            ),
        ),
    ]

    document_model: Type[QuittanceLoyerModel] = QuittanceLoyerModel
