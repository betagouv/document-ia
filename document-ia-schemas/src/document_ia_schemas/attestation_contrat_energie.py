from typing import Type, Optional
from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema


class BeneficiaireModel(BaseModel):
    nom: str = Field(
        description="Nom de famille du bénéficiaire",
        alias="Nom",
        examples=["MARTIN"],
    )
    prenom: Optional[str] = Field(
        default=None,
        description="Prénom du bénéficiaire",
        alias="Prénom",
        examples=["Sophie"],
    )


class AttestationContratEnergieModel(BaseModel):
    date_emission: Optional[str] = Field(
        default=None,
        description="Date d'émission de l'attestation (format JJ/MM/AAAA)",
        alias="Date d'émission",
        examples=["15/01/2024"],
    )
    nom_fournisseur: Optional[str] = Field(
        default=None,
        description="Nom ou raison sociale du fournisseur de service",
        alias="Nom Fournisseur",
        examples=["EDF", "ENGIE", "TOTAL ENERGIES"],
    )
    siret_fournisseur: Optional[str] = Field(
        default=None,
        description="Numéro SIRET du fournisseur de service (14 chiffres)",
        alias="SIRET du Fournisseur",
        examples=["12345678900012"],
    )
    beneficiaires: list[BeneficiaireModel] = Field(
        description="Liste des bénéficiaires du contrat",
        alias="Bénéficiaires",
        examples=[
            [{"nom": "DUPONT", "prenom": "Jean"}, {"nom": "DUPONT", "prenom": "Marie"}],
        ]
    )
    adresse_beneficiaire: Optional[str] = Field(
        default=None,
        description="Adresse postale complète du bénéficiaire (adresse de livraison du service)",
        alias="Adresse du bénéficiaire",
        examples=["10 RUE DE LA PAIX 75001 PARIS"],
    )
    numero_contrat: Optional[str] = Field(
        default=None,
        description="Numéro de contrat ou d'abonnement avec le fournisseur",
        alias="Numéro de contrat",
        examples=["1234567890"],
        json_schema_extra={
            "metrics": "equality"
        }
    )
    date_debut_contrat: Optional[str] = Field(
        default=None,
        description="Date de début du contrat (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de début du contrat",
        examples=["01/01/2024"],
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

    document_model: Type[AttestationContratEnergieModel] = AttestationContratEnergieModel
