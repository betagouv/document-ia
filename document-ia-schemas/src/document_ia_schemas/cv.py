from typing import Type, List, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.field_metrics import Metric


class CVExperienceModel(BaseModel):
    title: str = Field(
        description="Intitulé du poste",
        examples=["Chargée / chargé de la rénovation urbaine", "Secrétaire médical"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    company: str = Field(
        description="Nom de l'employeur",
        examples=["Direction Départementale des Territoires", "CHU Angers"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    sector: Optional[str] = Field(
        default=None,
        description="Secteur d'activité",
        examples=["Logement", "Santé"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    description: str = Field(
        description="Description du poste et missions",
        examples=[
            "Propose les options stratégiques que l'état fait valoir dans le champ de la rénovation urbaine.\nMobilise les acteurs locaux, négocie, suit et évalue leurs engagements.",
            "Accueillir et renseigner les patients, planifier les activités (agenda des consultations, admissions, convocations, etc.)\nGérer, saisir et classer les informations relatives au dossier patient"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class CVModel(BaseModel):
    experiences: List[CVExperienceModel] = Field(
        description="Liste des expériences professionnelles"
    )
    skills: List[str] = Field(
        description="Liste des compétences",
        examples=[
            [
                "Promouvoir une action, une démarche",
                "Connaisance de la Politique sociale du logement",
                "Faire preuve d'initiative",
            ],
            [
                "Connaissance du vocabulaire médical",
                "Elaborer, adapter et optimiser le planning de travail, de rendez-vous, des visites",
                "Utiliser les outils bureautiques et les logiciels métiers"
            ]
        ]
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
    document_model: Type[CVModel] = CVModel
