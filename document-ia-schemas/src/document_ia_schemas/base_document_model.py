from typing import Literal

from pydantic import BaseModel, Field


class BaseDocumentModel(BaseModel):
    status: Literal["success"] = Field(
        default='success',
        description="À utiliser UNIQUEMENT si le document est correctement extrait et validé.",
        examples=["success"]
    )


class EchecExtraction(BaseModel):
    status: Literal["failure"] = Field(
        'failure',
        description="À utiliser UNIQUEMENT si le document n'a pas pu être extrait ou validé.",
        examples=["failure"]
    )
    raison: str = Field(
        description="Explique brièvement pourquoi l'extraction a échoué.",
        examples=["The document is empty"]
    )
