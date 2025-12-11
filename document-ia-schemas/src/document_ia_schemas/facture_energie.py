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


class FactureEnergieModel(BaseModel):
    date_emission: Optional[str] = Field(
        default=None,
        description="Date d'émission de la facture (format JJ/MM/AAAA)",
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
        description="Liste des bénéficiaires du service",
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
    )
    numero_facture: Optional[str] = Field(
        default=None,
        description="Numéro unique de la facture",
        alias="Numéro de facture",
        examples=["FAC-2024-001234"],
        json_schema_extra={
            "metrics": "equality"
        }
    )
    montant_ttc: Optional[float] = Field(
        default=None,
        description="Montant total toutes taxes comprises (TTC) en euros",
        alias="Montant TTC",
        examples=[125.50],
    )


class FactureEnergieExtractSchema(BaseDocumentTypeSchema[FactureEnergieModel]):
    type: str = "facture_energie"
    name: str = "Facture d'énergie"
    description: list[str] = [
        "Document émis par un fournisseur de service facturant un service d'énergie.",
        "Mentions \"Facture\", \"Facture d'énergie\", ou \"Facture d'électricité\"",
        "Nom et coordonnées du bénéficiaire",
        "Nom et coordonnées du fournisseur de service",
        "Date de la facture",
        "Détails du service (électricité, énergie, télécom, etc.)",
        "Numéro de facture",
        "Montant TTC",
        "Signature et cachet du fournisseur",
    ]

    document_model: Type[FactureEnergieModel] = FactureEnergieModel
