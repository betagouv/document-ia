from datetime import date
from typing import Optional, Type

from document_ia_schemas.base_document_type_schema import FuzzyDate
from pydantic import BaseModel, Field, model_validator

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class AccessoireModel(BaseModel):
    intitule: Optional[str] = Field(
        default=None,
        description=(
            "Intitulé de l'accessoire (ex. : régulation, thermostat, filtre, pot à boue, "
            "soupape, raccords, liaisons frigorifiques, supports, protections électriques)."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    prix_ht: Optional[float] = Field(
        default=None,
        description="Prix HT en euros de l'accessoire.",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )


class PrixWithExplanation(BaseModel):
    explanation: Optional[str] = Field(
        default=None,
        description=(
            "Explication justifiant le raisonnement. "
            "OBLIGATOIRE lorsque prix_ht est null : préciser pourquoi aucun prix n'a "
            "pu être identifié (ex. : prix inclus dans un forfait global, prestation "
            "non mentionnée dans le devis)."
        ),
    )
    prix_ht: Optional[float] = Field(
        default=None,
        description=(
            "Prix HT en euros. null si aucun montant n'est explicitement chiffré dans "
            "le devis (dans ce cas, renseigner obligatoirement explanation)."
        ),
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )

    @model_validator(mode="after")
    def _require_explanation_when_price_is_null(self) -> "PrixWithExplanation":
        if self.prix_ht is None and not (self.explanation and self.explanation.strip()):
            raise ValueError(
                "explanation est obligatoire lorsque prix_ht est null."
            )
        return self


class DevisPacModel(BaseModel):
    siret: Optional[str] = Field(
        default=None,
        description="Numéro SIRET de l'entreprise installatrice et émettrice du devis (14 chiffres)",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    date_emission: FuzzyDate = Field(
        default=None,
        description="Date d'émission du devis",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    code_postal: Optional[str] = Field(
        default=None,
        description=(
            "Code postal du lieu des travaux "
            "(ex. : 13013, 92500). "
            "Si non identifiable dans le devis, écrire : Non renseigné."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    marque: Optional[str] = Field(
        default=None,
        description=(
            "Marque commerciale du fabricant de la PAC "
            "(ex. : Daikin, Atlantic, Viessmann, Mitsubishi, Vaillant). "
            "Extraire du devis uniquement."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    modele: Optional[str] = Field(
        default=None,
        description=(
            "Référence commerciale exacte du modèle de PAC "
            "(ex. : Altherma 3H HT, Aroshift 5, Vitodens 200-W)."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    puissance: Optional[str] = Field(
        default=None,
        description=(
            "Puissance thermique nominale de la PAC en kW, avec les conditions si "
            "précisées (ex. : 8 kW A7/W35)."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    alimentation_electrique: Optional[str] = Field(
        default=None,
        description=(
            "Alimentation électrique de la PAC : écrire « mono » si monophasé / 230V, "
            "« triphasé » si triphasé / 400V. Sinon : Non renseigné."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    prix_pac_ht: PrixWithExplanation = Field(
        description=(
            "Prix de la PAC principale (unité extérieure + intérieure) hors accessoires "
            "séparés, hors main-d'œuvre, hors aides. Montant HT en euros. "
            "Si le devis présente un forfait global sans détail matériel, y inscrire le "
            "forfait global."
        ),
    )
    accessoires: list[AccessoireModel] = Field(
        default_factory=list,
        description=(
            "Liste des accessoires chiffrés (régulation, thermostat, filtre, pot à boue, "
            "soupape, raccords, liaisons frigorifiques, supports, protections électriques, "
            "etc.), chacun avec son intitulé et son prix HT. "
            "Ne pas inclure la PAC principale ni la main-d'œuvre."
        ),
    )
    prix_pose_ht: PrixWithExplanation = Field(
        description=(
            "Prix HT en euros de la main-d'œuvre (ex. pose, installation, raccordement, "
            "forfait pose ou forfait main-d'œuvre)."
        ),
    )
    prix_mise_en_service_ht: PrixWithExplanation = Field(
        description=(
            "Prix HT en euros correspondant aux montants explicitement chiffrés liés à la "
            "« mise en service », « mise en route », « paramétrage », « réglages » ou "
            "« mise en main ». Si inclus dans un forfait main-d'oeuvre, laisser vide."
        ),
    )
    prix_changement_emetteur_ht: PrixWithExplanation = Field(
        description=(
            "Prix HT en euros correspondant aux montants explicitement chiffrés liés au "
            "remplacement de radiateurs, plancher chauffant ou autres émetteurs de "
            "chaleur."
        ),
    )
    prix_depose_chaudiere_ht: PrixWithExplanation = Field(
        description=(
            "Prix HT en euros de la dépose, l'enlèvement ou l'évacuation de l'ancienne "
            "chaudière. Si inclus dans un forfait, laisser vide."
        ),
    )


class DevisPacExtractSchema(BaseDocumentTypeSchema[DevisPacModel]):
    type: str = "devis_pac"
    name: str = "Devis PAC"
    description: list[str] = [
        "Devis d'installation d'une pompe à chaleur Air/Eau (PAC).",
        "Émis par un installateur ou un professionnel du chauffage.",
        "Décrit la PAC Air/Eau proposée : marque, modèle, puissance et alimentation électrique.",
        "Détaille les prix : matériel HT/TTC, accessoires, pose, mise en service.",
        "Peut mentionner le changement d'émetteurs, travaux annexes, dépose chaudière, désembouage.",
        "Peut mentionner d'autres travaux de rénovation énergétique, ne prends en compte que les travaux liés à la PAC.",
    ]
    examples: list[DevisPacModel] = [
        DevisPacModel(
            siret="12345678900012",
            date_emission=date(2026, 1, 15),
            code_postal="75017",
            marque="Daikin",
            modele="Altherma 3H HT",
            puissance="8 kW A7/W35",
            alimentation_electrique="mono",
            prix_pac_ht=PrixWithExplanation(
                prix_ht=8500,
                explanation="Prix de l'unité extérieure et intérieure indiqué sur le devis.",
            ),
            accessoires=[
                AccessoireModel(intitule="Régulation connectée", prix_ht=450.0),
                AccessoireModel(intitule="Pot à boue", prix_ht=120.0),
                AccessoireModel(intitule="Liaisons frigorifiques", prix_ht=630.0),
            ],
            prix_pose_ht=PrixWithExplanation(
                prix_ht=2500,
                explanation="Ligne « forfait pose » du devis.",
            ),
            prix_mise_en_service_ht=PrixWithExplanation(
                prix_ht=350,
                explanation="Ligne « mise en service » chiffrée séparément.",
            ),
            prix_changement_emetteur_ht=PrixWithExplanation(
                prix_ht=1800,
                explanation="Remplacement de radiateurs chiffré sur le devis.",
            ),
            prix_depose_chaudiere_ht=PrixWithExplanation(
                prix_ht=450,
                explanation="Dépose de l'ancienne chaudière chiffrée séparément.",
            ),
        ),
        DevisPacModel(
            siret="12345678900012",
            date_emission=date(2026, 1, 15),
            code_postal="69003",
            marque="Atlantic",
            modele="Aroshift 5",
            puissance="11 kW A7/W35",
            alimentation_electrique="triphasé",
            prix_pac_ht=PrixWithExplanation(
                prix_ht=9200,
                explanation="Prix matériel de la PAC indiqué sur le devis.",
            ),
            accessoires=[
                AccessoireModel(intitule="Thermostat d'ambiance", prix_ht=200.0),
                AccessoireModel(intitule="Supports antivibratiles", prix_ht=150.0),
                AccessoireModel(intitule="Protections électriques", prix_ht=600.0),
            ],
            prix_pose_ht=PrixWithExplanation(
                prix_ht=2800,
                explanation="Le prix de la pose est inclus dans le forfait main-d'oeuvre du devis.",
            ),
            prix_mise_en_service_ht=PrixWithExplanation(
                prix_ht=None,
                explanation="Compris dans le forfait main-d'oeuvre.",
            ),
            prix_changement_emetteur_ht=PrixWithExplanation(
                prix_ht=None,
                explanation="Compris dans le forfait main-d'oeuvre.",
            ),
            prix_depose_chaudiere_ht=PrixWithExplanation(
                prix_ht=500,
                explanation="Dépose de l'ancienne chaudière chiffrée séparément.",
            ),
        ),
    ]

    document_model: Type[DevisPacModel] = DevisPacModel
