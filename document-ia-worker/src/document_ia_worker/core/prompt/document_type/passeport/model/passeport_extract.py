from typing import Optional

from pydantic import BaseModel, Field


class PassportExtract(BaseModel):
    numero_document: str = Field(
        title="Numero du passeport",
        description="Identifiant unique / Numéro du passeport (format alphanumérique)",
    )
    nom: str = Field(
        title="Nom",
        description="Nom de famille du titulaire (en majuscules sur le document)",
    )
    prenom: str = Field(
        title="Prénom",
        description="Prénom du titulaire (premier prénom)",
    )
    lieu_naissance: str = Field(
        title="Lieu de naissance",
        description="Lieu de naissance du titulaire (ville)",
    )
    nationalite: str = Field(
        title="Nationalité",
        description="Nationalité du titulaire",
    )
    bande_mrz: str = Field(
        title="Bande MRZ",
        description="Bande MRZ du passeport",
    )
    date_delivrance: Optional[str] = Field(
        default=None,
        title="Date d'émission",
        description="Date d'émission du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    date_expiration: Optional[str] = Field(
        default=None,
        title="Date d'expiration",
        description="Date limite de validité du passeport (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    date_naissance: Optional[str] = Field(
        default=None,
        title="Date de naissance",
        description="Date de naissance du titulaire (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
