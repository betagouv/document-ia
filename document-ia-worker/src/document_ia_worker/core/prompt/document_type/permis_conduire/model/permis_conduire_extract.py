from typing import Optional

from pydantic import BaseModel, Field


class PermisConduireExtract(BaseModel):
    numero_document: str = Field(
        title="Numéro du permis",
        description="Identifiant unique du permis de conduire (format alphanumérique).",
    )
    nom: str = Field(
        title="Nom",
        description="Nom de famille du titulaire (en majuscules sur le document).",
    )
    prenom: str = Field(
        title="Prénom",
        description="Prénom du titulaire (premier prénom).",
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        title="Lieu de naissance",
        description="Lieu de naissance du titulaire (ville). Si absente, renseigner `null`.",
    )
    nationalite: Optional[str] = Field(
        default=None,
        title="Nationalité",
        description="Nationalité du titulaire.",
    )
    date_naissance: Optional[str] = Field(
        default=None,
        title="Date de naissance",
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    date_delivrance: Optional[str] = Field(
        default=None,
        title="Date de délivrance",
        description="Date de délivrance du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    date_expiration: Optional[str] = Field(
        default=None,
        title="Date d'expiration",
        description="Date limite de validité du permis de conduire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    adresse: Optional[str] = Field(
        default=None,
        title="Adresse",
        description="Adresse de résidence du titulaire. Si absente, renseigner `null`.",
    )
