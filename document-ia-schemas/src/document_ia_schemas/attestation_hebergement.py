from datetime import date
from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema, Metric
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.identity import Identity


class PersonneAttestationHebergementModel(BaseModel):
    identite: Identity = Field(
        default=None,
        description="Nom et prenoms de la personne.",
        examples=["DUPONT Camille"],
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        },
    )
    date_naissance: FuzzyDate = Field(
        default=None,
        description="Date de naissance de la personne.",
        examples=["1990-05-12"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Lieu de naissance de la personne.",
        examples=["Lyon"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class AttestationHebergementModel(BaseModel):
    hebergeur: Optional[PersonneAttestationHebergementModel] = Field(
        default=None,
        description="Identite complete de l'hebergeur.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    heberge: Optional[PersonneAttestationHebergementModel] = Field(
        default=None,
        description="Identite complete de la personne hebergee.",
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    adresse_complete_hebergement: Optional[str] = Field(
        default=None,
        description="Adresse complete du lieu de residence.",
        examples=["10 RUE DE LA PAIX 75001 PARIS"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_redaction: FuzzyDate = Field(
        default=None,
        description="Date de redaction de l'attestation.",
        examples=["2026-04-30"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    lieu_redaction: Optional[str] = Field(
        default=None,
        description="Lieu de redaction de l'attestation.",
        examples=["Paris"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    presence_signature_hebergeur: Optional[bool] = Field(
        default=None,
        description="Indique si la signature de l'hebergeur est detectee.",
        examples=[True],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )


class AttestationHebergementExtractSchema(BaseDocumentTypeSchema[AttestationHebergementModel]):
    type: str = "attestation_hebergement"
    name: str = "Attestation d'hebergement"
    description: list[str] = [
        "Lettre signee par l'hebergeur certifiant sur l'honneur l'hebergement a titre gratuit",
        "Contient l'identite de l'hebergeur et de la personne hebergee",
        "Contient l'adresse complete d'hebergement",
        "Mentionne en general un hebergement depuis plus de 3 mois",
        "Indique la date et le lieu de redaction ainsi que la signature de l'hebergeur",
    ]
    examples: list[AttestationHebergementModel] = [
        AttestationHebergementModel(
            hebergeur=PersonneAttestationHebergementModel(
                identite="DUPONT Marie",
                date_naissance=date(1985, 3, 14),
                lieu_naissance="Lyon",
            ),
            heberge=PersonneAttestationHebergementModel(
                identite="MARTIN Theo",
                date_naissance=date(1998, 9, 20),
                lieu_naissance="Marseille",
            ),
            adresse_complete_hebergement="10 RUE DE LA PAIX 75001 PARIS",
            date_redaction=date(2026, 4, 30),
            lieu_redaction="Paris",
            presence_signature_hebergeur=True,
        ),
        AttestationHebergementModel(
            hebergeur=PersonneAttestationHebergementModel(
                identite="BERNARD Chloe",
                date_naissance=date(1979, 11, 2),
                lieu_naissance="Nantes",
            ),
            heberge=PersonneAttestationHebergementModel(
                identite="BERNARD Alex",
                date_naissance=date(2001, 7, 15),
                lieu_naissance="Nantes",
            ),
            adresse_complete_hebergement="22 AVENUE VICTOR HUGO 69003 LYON",
            date_redaction=date(2026, 3, 28),
            lieu_redaction="Lyon",
            presence_signature_hebergeur=True,
        ),
    ]

    document_model: Type[AttestationHebergementModel] = AttestationHebergementModel
