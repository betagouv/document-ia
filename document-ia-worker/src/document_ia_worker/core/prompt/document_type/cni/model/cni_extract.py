from typing import Optional

from pydantic import BaseModel, Field


class CNIExtract(BaseModel):
    numero_document: str
    nom: str
    prenom: str
    lieu_naissance: str
    nationalite: str
    date_delivrance: Optional[str] = Field(default=None)
    date_expiration: Optional[str] = Field(default=None)
    date_naissance: Optional[str] = Field(default=None)
    bande_mrz: Optional[str] = Field(default=None)
