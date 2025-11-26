from typing import Type, Optional

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema


class BulletinSalaireModel(BaseModel):
    # --- Identité Employeur ---
    nom_employeur: Optional[str] = Field(
        description="Nom ou raison sociale de l'employeur",
        alias="Employeur",
        examples=["ACME CORPORATION", "BOULANGERIE DUPONT"],
        default=None
    )
    siret: Optional[str] = Field(
        description="Numéro SIRET de l'employeur (14 chiffres)",
        alias="SIRET Employeur",
        examples=["12345678900012"],
        default=None
    )

    # --- Identité Salarié ---
    nom_salarie: str = Field(
        description="Nom de famille du salarié",
        alias="Nom du salarié",
        examples=["MARTIN"],
    )
    prenom_salarie: str = Field(
        description="Prénom du salarié",
        alias="Prénom du salarié",
        examples=["THOMAS"],
    )
    adresse_salarie: Optional[str] = Field(
        description="Adresse postale complète du salarié",
        alias="Adresse du salarié",
        examples=["10 RUE DE LA PAIX 75000 PARIS"],
        default=None
    )

    # --- Détails du contrat ---
    periode_debut: Optional[str] = Field(
        description="Date de début de la période de paie concernée (format JJ/MM/AAAA)",
        alias="Période début",
        examples=["01/01/2024"],
        default=None
    )
    periode_fin: Optional[str] = Field(
        description="Date de fin de la période de paie concernée (format JJ/MM/AAAA)",
        alias="Période fin",
        examples=["31/01/2024"],
        default=None
    )
    date_paiement: Optional[str] = Field(
        description="Date de mise en paiement du salaire (format JJ/MM/AAAA)",
        alias="Date de paiement",
        examples=["02/02/2024"],
        default=None
    )
    emploi: Optional[str] = Field(
        description="Intitulé du poste ou de l'emploi occupé",
        alias="Emploi / Qualification",
        examples=["INGENIEUR D'ETUDES", "VENDEUR"],
        default=None
    )
    anciennete: Optional[str] = Field(
        description="Date d'ancienneté ou d'entrée dans l'entreprise (format JJ/MM/AAAA)",
        alias="Date d'ancienneté",
        examples=["15/05/2018"],
        default=None
    )

    # --- Données Financières ---
    salaire_brut: Optional[float] = Field(
        description="Montant total du salaire brut (Total Brut)",
        alias="Salaire Brut",
        examples=["3500.00", "2 150,50"],
        default=None
    )
    net_imposable: Optional[float] = Field(
        description="Montant du Net Imposable (base pour les impôts)",
        alias="Net Imposable",
        examples=["2800.00"],
        default=None
    )
    impot_sur_le_revenu: Optional[float] = Field(
        description="Montant du prélèvement à la source (PAS) si présent",
        alias="Impôt à la source",
        examples=["150.20"],
        default=None
    )
    net_a_payer: float = Field(
        description="Montant final Net à Payer (le montant viré sur le compte bancaire, en bas de page en gras)",
        alias="Net à Payer",
        examples=["2649.80"],
    )
    net_social: Optional[float] = Field(
        description="Montant Net Social (mention obligatoire depuis 2023/2024)",
        alias="Montant Net Social",
        examples=["2700.00"],
        default=None
    )
    cumul_imposable_annuel: Optional[float] = Field(
        description="Cumul annuel du Net Imposable (souvent en bas de page)",
        alias="Cumul Imposable Annuel",
        examples=["32500.00"],
        default=None
    )


class BulletinSalaireExtractSchema(BaseDocumentTypeSchema[BulletinSalaireModel]):
    type: str = "bulletin_salaire"
    name: str = "Bulletin de salaire"
    description: list[str] = [
        "Document officiel de paie (Fiche de paie / Bulletin de salaire)",
        "Contient des mentions comme 'Bulletin de paie', 'Salaire', 'Employeur', 'Salarié'",
        "Présence d'un tableau avec des colonnes (libellé, base, taux, montant)",
        "Contient des montants Brut, Net Imposable et Net à Payer",
        "Mentionne souvent l'URSSAF, la CSG, la CRDS",
        "Présence obligatoire du montant 'Net Social' sur les fiches récentes",
    ]
    document_model: Type[BulletinSalaireModel] = BulletinSalaireModel
