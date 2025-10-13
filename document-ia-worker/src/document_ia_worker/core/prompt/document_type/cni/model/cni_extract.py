from typing import Optional

from pydantic import BaseModel


class CNIExtract(BaseModel):
    numero_document: str
    nom: str
    prenom: str
    lieu_naissance: str
    nationalite: str
    date_delivrance: Optional[str] = None
    date_expiration: Optional[str] = None
    date_naissance: Optional[str] = None
    bande_mrz: Optional[str] = None
