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


class QuittanceLoyerModel(BaseModel):
    date_emission: Optional[str] = Field(
        default=None,
        description="Date d'émission de la quittance (format JJ/MM/AAAA)",
        alias="Date d'émission",
        examples=["15/01/2024"],
    )
    beneficiaires: list[BeneficiaireModel] = Field(
        description="Liste des bénéficiaires (locataires) de la quittance",
        alias="Bénéficiaires",
        examples=[
            [{"nom": "DUPONT", "prenom": "Jean"}, {"nom": "DUPONT", "prenom": "Marie"}],
        ]
    )
    adresse_beneficiaire: Optional[str] = Field(
        default=None,
        description="Adresse postale complète du bénéficiaire (adresse du logement)",
        alias="Adresse du bénéficiaire",
        examples=["10 RUE DE LA PAIX 75001 PARIS"],
    )
    periode_debut: Optional[str] = Field(
        default=None,
        description="Date de début de la période couverte par la quittance (format JJ/MM/AAAA)",
        alias="Période début",
        examples=["01/01/2024"],
    )
    periode_fin: Optional[str] = Field(
        default=None,
        description="Date de fin de la période couverte par la quittance (format JJ/MM/AAAA)",
        alias="Période fin",
        examples=["31/01/2024"],
    )
    montant_total: Optional[float] = Field(
        default=None,
        description="Montant total du loyer payé en euros (incluant les charges)",
        alias="Montant total",
        examples=[850.00],
    )
    montant_hors_charges: Optional[float] = Field(
        default=None,
        description="Montant du loyer hors charges en euros, si absent, renseigner `null`.",
        alias="Montant hors charges",
        examples=[700.00],
    )


class QuittanceLoyerExtractSchema(BaseDocumentTypeSchema[QuittanceLoyerModel]):
    type: str = "quittance_loyer"
    name: str = "Quittance de loyer"
    description: list[str] = [
        "La quittance est un reçu pour un paiement spécifique (généralement mensuel)",
        "Document officiel attestant du paiement d'un loyer pour une période donnée",
        "Contient les termes \"quittance\", \"loyer\", \"terme\", \"paiement\", \"solde\"",
        "Mentionne le montant précis du loyer et éventuellement des charges",
        "Identifie clairement un bailleur (propriétaire/agence) et un ou plusieurs locataires",
        "Précise l'adresse du logement et la période concernée (mois/trimestre)",
        "Généralement datée et signée par le bailleur",
        "La quittance a un caractère transactionnel",
    ]

    document_model: Type[QuittanceLoyerModel] = QuittanceLoyerModel
