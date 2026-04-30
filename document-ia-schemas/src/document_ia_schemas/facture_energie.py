from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema, Metric
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.identity import Identity


class BeneficiaireModel(BaseModel):
    identite: Identity = Field(
        default=None,
        description="Nom et prénom du bénéficiaire",
        examples=["DUPONT Camille"],
        json_schema_extra={
            "metrics": [
                Metric.TOKEN_SET_EQUALITY,
                Metric.LEVENSHTEIN_DISTANCE,
            ]
        }
    )


class FactureEnergieModel(BaseModel):
    date_emission: FuzzyDate = Field(
        default=None,
        description="Date d'émission de la facture",
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
        description="Liste des bénéficiaires du service",
        default_factory=list,
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
    numero_facture: Optional[str] = Field(
        default=None,
        description="Numéro unique de la facture",
        examples=["FAC-2024-001234"],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    montant_ttc: Optional[float] = Field(
        default=None,
        description="Montant total toutes taxes comprises (TTC) en euros",
        examples=[125.50],
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
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
    examples: list[FactureEnergieModel] = [
        FactureEnergieModel(
            date_emission="15/01/2024",
            nom_fournisseur="EDF",
            siret_fournisseur="55208131766522",
            beneficiaires=[BeneficiaireModel(identite="DUPONT Camille")],
            adresse_beneficiaire="10 RUE DE LA PAIX 75001 PARIS",
            numero_contrat="ELEC-458796214",
            numero_facture="FAC-2024-001234",
            montant_ttc=125.50,
        ),
        FactureEnergieModel(
            date_emission="28/02/2024",
            nom_fournisseur="ENGIE",
            siret_fournisseur="54210765113030",
            beneficiaires=[
                BeneficiaireModel(identite="MARTIN Nora"),
                BeneficiaireModel(identite="MARTIN Alex"),
            ],
            adresse_beneficiaire="22 AVENUE VICTOR HUGO 69003 LYON",
            numero_contrat="GAZ-998745120",
            numero_facture="FAC-2024-004892",
            montant_ttc=214.90,
        ),
    ]

    document_model: Type[FactureEnergieModel] = FactureEnergieModel
