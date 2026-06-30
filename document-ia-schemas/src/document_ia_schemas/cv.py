from typing import Type, List, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class CVExperienceModel(BaseModel):
    title: Optional[str] = Field(
        description="Intitulé du poste",
        default=None,
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    company: Optional[str] = Field(
        default=None,
        description="Nom de l'employeur",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    sector: Optional[str] = Field(
        default=None,
        description="Secteur d'activité",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    description: Optional[str] = Field(
        default=None,
        description="Description du poste et missions",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class CVModel(BaseModel):
    experiences: List[CVExperienceModel] = Field(
        description="Liste des expériences professionnelles"
    )
    skills: List[str] = Field(
        description="Liste des compétences",
    )


class CVExtractSchema(BaseDocumentTypeSchema[CVModel]):
    type: str = "cv"
    name: str = "CV (Expériences et Compétences)"
    description: list[str] = [
        "Document CV (Curriculum Vitae) contenant les informations professionnelles",
        "Extrait les expériences professionnelles avec poste, employeur, secteur et description",
        "Extrait la liste des compétences",
        "Format PDF ou document texte standard",
    ]
    examples: list[CVModel] = [
        CVModel(
            experiences=[
                CVExperienceModel(
                    title="Chargée / chargé de la rénovation urbaine",
                    company="Direction Départementale des Territoires",
                    sector="Logement",
                    description=(
                        "Propose les options stratégiques que l'état fait valoir dans le champ "
                        "de la rénovation urbaine.\nMobilise les acteurs locaux, négocie, suit "
                        "et évalue leurs engagements."
                    ),
                )
            ],
            skills=[
                "Promouvoir une action, une démarche",
                "Connaisance de la Politique sociale du logement",
                "Faire preuve d'initiative",
            ],
        ),
        CVModel(
            experiences=[
                CVExperienceModel(
                    title="Secrétaire médical",
                    company="CHU Angers",
                    sector="Santé",
                    description=(
                        "Accueillir et renseigner les patients, planifier les activités "
                        "(agenda des consultations, admissions, convocations, etc.)\nGérer, "
                        "saisir et classer les informations relatives au dossier patient"
                    ),
                )
            ],
            skills=[
                "Connaissance du vocabulaire médical",
                "Elaborer, adapter et optimiser le planning de travail, de rendez-vous, des visites",
                "Utiliser les outils bureautiques et les logiciels métiers",
            ],
        ),
    ]
    document_model: Type[CVModel] = CVModel
