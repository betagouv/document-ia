from datetime import date
from typing import Type, Optional
from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema, Metric
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.identity import Identity


class BeneficiaireModel(BaseModel):
    identite: Identity = Field(
        default=None,
        description="Nom et prénom du bénéficiaire",
        examples=["MARTIN Sophie"],
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        }
    )


class AttestationContratEnergieModel(BaseModel):
    date_emission: FuzzyDate = Field(
        default=None,
        description="Date d'émission de l'attestation.",
        examples=["2026-04-01"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    nom_fournisseur: Optional[str] = Field(
        default=None,
        description="Nom ou raison sociale du fournisseur de service",
        examples=["EDF", "ENGIE", "TOTAL ENERGIES"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    siret_fournisseur: Optional[str] = Field(
        default=None,
        description="Numéro SIRET du fournisseur de service (14 chiffres)",
        examples=["12345678900012"],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    beneficiaires: list[BeneficiaireModel] = Field(
        description="Liste des bénéficiaires du contrat",
        default_factory=list,
        examples=[
            [{"identite": "DUPONT Jean"}, {"identite": "DUPONT Marie"}],
        ],
        json_schema_extra={"metrics": Metric.DEEP_EQUALITY},
    )
    adresse_beneficiaire: Optional[str] = Field(
        default=None,
        description="Adresse postale complète du bénéficiaire (adresse de livraison du service)",
        examples=["10 RUE DE LA PAIX 75001 PARIS"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    numero_contrat: Optional[str] = Field(
        default=None,
        description="Numéro de contrat ou d'abonnement avec le fournisseur",
        examples=["1234567890"],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    date_debut_contrat: FuzzyDate = Field(
        default=None,
        description="Date de début du contrat. Si absente, renseigner `null`.",
        examples=["2026-04-01"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )


class AttestationContratEnergieExtractSchema(BaseDocumentTypeSchema[AttestationContratEnergieModel]):
    type: str = "attestation_contrat_energie"
    name: str = "Attestation de contrat d'énergie"
    description: list[str] = [
        "Document émis par un fournisseur de service certifiant qu'un bénéficiaire a bien contracté avec le fournisseur.",
        "Mentions \"Attestation de contrat\", \"Certificat de contrat\", ou \"Contrat\"",
        "Nom et coordonnées du bénéficiaire",
        "Nom et coordonnées du fournisseur de service",
        "Date de début du contrat",
        "Détails du service (électricité, énergie, télécom, etc.)",
        "Numéro de contrat/abonnement",
        "Signature et cachet du fournisseur",
    ]
    examples: list[AttestationContratEnergieModel] = [
        AttestationContratEnergieModel(
            date_emission=date(2024,1, 15),
            nom_fournisseur="EDF",
            siret_fournisseur="55208131766522",
            beneficiaires=[BeneficiaireModel(identite="DUPONT Camille")],
            adresse_beneficiaire="10 RUE DE LA PAIX 75001 PARIS",
            numero_contrat="ELEC-458796214",
            date_debut_contrat=date(2024,1, 1),
        ),
        AttestationContratEnergieModel(
            date_emission=date(2024, 2, 28),
            nom_fournisseur="ENGIE",
            siret_fournisseur="54210765113030",
            beneficiaires=[
                BeneficiaireModel(identite="MARTIN Nora"),
                BeneficiaireModel(identite="MARTIN Alex"),
            ],
            adresse_beneficiaire="22 AVENUE VICTOR HUGO 69003 LYON",
            numero_contrat="GAZ-998745120",
            date_debut_contrat=date(2024, 1, 10),
        ),
    ]

    document_model: Type[AttestationContratEnergieModel] = AttestationContratEnergieModel
