from datetime import date
from enum import Enum
from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric
from document_ia_schemas.identity import Identity


class TypeRecoursDalo(str, Enum):
    LOGEMENT = "logement"
    HEBERGEMENT = "hebergement"


class SensDecisionComed(str, Enum):
    PRIORITAIRE_URGENT = "prioritaire_urgent"
    REJET = "rejet"
    IRRECEVABLE = "irrecevable"
    SANS_OBJET = "sans_objet"
    REORIENTATION = "reorientation"


class DecisionComedModel(BaseModel):
    departement_commission: Optional[str] = Field(
        default=None,
        description=(
            "Département de la commission de médiation, sans l'article (ex : Hérault)."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    numero_recours: Optional[str] = Field(
        default=None,
        description="Numéro d'enregistrement du recours, au format AAAA-DDD-NNNNNN.",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    type_recours: Optional[TypeRecoursDalo] = Field(
        default=None,
        description=(
            "Objet du recours : `logement` pour une offre de logement"
            " (article L.441-2-3, II, mentions « offre de logement »), `hebergement`"
            " pour un accueil en structure d'hébergement (article L.441-2-3, III,"
            " mentions « structure d'hébergement », « accueil » ou « hébergement »)."
        ),
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    demandeur: Identity = Field(
        default=None,
        description=(
            "Nom et prénom du requérant, sans civilité, au format NOM en majuscules"
            " suivi du ou des prénom(s) (ex : `MOREAU Élise`). Réordonner si l'OCR"
            " inverse prénom et nom."
        ),
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        },
    )
    date_reception_recours: FuzzyDate = Field(
        default=None,
        description=(
            "Date de réception du recours par le secrétariat de la commission "
            "(souvent dans un « Vu »). Ne pas utiliser la date de réception au tribunal"
            " (« TA … reçu le … »). Si absente, renseigner `null`."
        ),
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    motifs_recours: list[str] = Field(
        default_factory=list,
        description=(
            "Motif(s) invoqué(s) par le requérant : une entrée par case à cocher"
            " sélectionnée ou par élément de texte libre, tels qu'écrits sur la"
            " décision (y compris les libellés standard des cases)."
        ),
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    date_decision: FuzzyDate = Field(
        default=None,
        description=(
            "Date de la séance au cours de laquelle la commission a statué "
            "(mentions « séance du », « réunion du », « décision en date du » dans le"
            " corps), et non la date d'envoi du courrier. Si absente, renseigner"
            " `null`."
        ),
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    date_courrier: FuzzyDate = Field(
        default=None,
        description=(
            "Date d'envoi du courrier ou de la notification, en tête du document "
            "(formule « Fait à …, le … »). Ne pas confondre avec la date de séance."
            " Si absente, renseigner `null`."
        ),
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    sens_decision: Optional[SensDecisionComed] = Field(
        default=None,
        description=(
            "Sens de la décision, déterminé uniquement à partir du dispositif "
            "(articles numérotés après « Décide »), jamais à partir des considérants"
            " : `prioritaire_urgent` si le dispositif reconnaît le demandeur"
            " prioritaire ou fait droit au recours pour logement/hébergement en urgence"
            " ; `rejet` si le recours est rejeté (« rejette ») ; `irrecevable` si déclaré"
            " irrecevable ; `sans_objet` si sans objet ; `reorientation` si réorienté"
            " vers un autre dispositif ou mode d'accueil."
        ),
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    motifs_decision: list[str] = Field(
        default_factory=list,
        description=(
            "Synthèse courte des considérants qui fondent la décision : une phrase par"
            " considérant utile, sans recopier le dispositif ni les rappels de textes"
            " et de procédure."
        ),
        json_schema_extra={"metrics": Metric.SKIP},
    )
    tribunal_competent: Optional[str] = Field(
        default=None,
        description=(
            "Tribunal administratif compétent pour un recours contentieux, indiqué"
            " dans le paragraphe sur les voies et délais de recours, sans son adresse."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class DecisionComedExtractSchema(BaseDocumentTypeSchema[DecisionComedModel]):
    type: str = "decision_comed"
    name: str = "Décision de la commission de médiation DALO"
    description: list[str] = [
        "Décision d'une commission de médiation départementale sur un recours pour le "
        "droit au logement opposable (DALO)",
        'Contient des mentions comme "Droit au logement opposable", "Loi n°2007-290 du '
        '5 mars 2007" et "Commission de médiation"',
        "Émise par la préfecture ou la direction départementale de l'emploi, du "
        "travail et des solidarités (DDETS)",
        'Structure en "Vu", "Considérant", puis "Décide" avec des articles numérotés',
        "Numéro de recours, nom du requérant et sens de la décision",
        "Indique le tribunal administratif compétent et les voies de recours en fin de "
        "document",
        "Ignorer les bandeaux de réception type « TA … reçu le … » ajoutés en pièce "
        "contentieuse",
        "Peut exister en version « décision et notification » avec deux dates distinctes"
        " (séance et envoi)",
        "Un fichier ne contenant qu'un verso ou une page partielle peut être incomplet",
    ]
    examples: list[DecisionComedModel] = [
        DecisionComedModel(
            departement_commission="Loire-Atlantique",
            numero_recours="2023-044-000417",
            type_recours=TypeRecoursDalo.HEBERGEMENT,
            demandeur="MOREAU Élise",
            date_reception_recours=date(2023, 2, 14),
            motifs_recours=["Sans domicile"],
            date_decision=date(2023, 5, 11),
            date_courrier=date(2023, 5, 15),
            sens_decision=SensDecisionComed.PRIORITAIRE_URGENT,
            motifs_decision=[
                "Requérante sans domicile depuis plus de six mois",
                "Démarches préalables auprès du service d'accueil restées sans réponse",
            ],
            tribunal_competent="Tribunal administratif de Nantes",
        ),
        DecisionComedModel(
            departement_commission="Hérault",
            numero_recours="2023-034-000177",
            type_recours=TypeRecoursDalo.LOGEMENT,
            demandeur="VAISSIERES Cédric",
            date_reception_recours=date(2023, 1, 23),
            motifs_recours=[
                "Délai anormalement long de 36 mois sans proposition de logement",
            ],
            date_decision=date(2023, 10, 3),
            date_courrier=date(2023, 10, 17),
            sens_decision=SensDecisionComed.REJET,
            motifs_decision=[
                "Le requérant déclare demeurer chez un tiers",
                "Aucun nouvel élément pour justifier l'urgence d'attribuer un logement",
            ],
            tribunal_competent="Tribunal administratif de Montpellier",
        ),
        DecisionComedModel(
            departement_commission="Rhône",
            numero_recours="2019-069-000512",
            type_recours=TypeRecoursDalo.LOGEMENT,
            demandeur="BERNARD Claire",
            date_reception_recours=date(2019, 3, 11),
            motifs_recours=[
                "Dépourvu(e) de logement/Hébergé(e) chez un particulier",
                "Précisions complémentaires du requérant sur sa situation familiale",
            ],
            date_decision=date(2019, 7, 2),
            date_courrier=date(2019, 7, 24),
            sens_decision=SensDecisionComed.REORIENTATION,
            motifs_decision=[
                "Accompagnement social nécessaire pour stabiliser la situation",
                "Offre de logement non adaptée à la situation particulière du requérant",
            ],
            tribunal_competent="Tribunal administratif de Lyon",
        ),
    ]
    document_model: Type[DecisionComedModel] = DecisionComedModel
