from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema


class AttestationAffiliationModel(BaseModel):
    # Informations de l'affilié
    nom_structure: str = Field(
        description="Nom de la structure affiliée",
        alias="Nom de la structure",
        examples=["Association Sportive de Paris"],
    )
    adresse_siege_structure: str = Field(
        description="Adresse complète du siège social de la structure affiliée",
        alias="Adresse du siège social",
        examples=["123 Rue de la République, 75001 Paris"],
    )
    numero_siret_structure: str = Field(
        description="Numéro SIRET de la structure affiliée (14 chiffres)",
        alias="Numéro SIRET",
        examples=["12345678901234"],
    )
    # Informations de l'organisme d'affiliation
    nom_organisme: str = Field(
        description="Nom de l'organisme d'affiliation",
        alias="Nom de l'organisme d'affiliation",
        examples=["Fédération Française de Sport"],
    )
    adresse_siege_organisme: str = Field(
        description="Adresse complète du siège social de l'organisme d'affiliation",
        alias="Adresse du siège de l'organisme d'affiliation",
        examples=["456 Avenue des Sports, 75012 Paris"],
    )
    nom_president_organisme: Optional[str] = Field(
        default=None,
        description="Nom du président de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
        alias="Nom du président de l'organisme d'affiliation",
        examples=["MARTIN Jean"],
    )
    telephone_organisme: Optional[str] = Field(
        default=None,
        description="Numéro de téléphone de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
        alias="Téléphone de l'organisme d'affiliation",
        examples=["01 23 45 67 89"],
    )
    email_organisme: str = Field(
        default=None,
        description="Adresse email de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
        alias="Email de l'organisme d'affiliation",
        examples=["contact@federation-sport.fr"],
    )
    # Date d'émission
    date_emission: Optional[str] = Field(
        description="Date d'émission du document (format JJ/MM/AAAA)",
        alias="Date d'émission",
        examples=["15/03/2024"],
    )
    # Période de validité
    date_debut_validite: Optional[str] = Field(
        default=None,
        description="Date de début de validité de l'attestation (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de début de validité",
        examples=["01/01/2024"],
    )
    date_fin_validite: Optional[str] = Field(
        default=None,
        description="Date de fin de validité de l'attestation (format JJ/MM/AAAA). Si absente, renseigner `null`.",
        alias="Date de fin de validité",
        examples=["31/12/2024"],
    )

class AttestationAffiliationExtractSchema(BaseDocumentTypeSchema[AttestationAffiliationModel]):
    type: str = "attestation_affiliation"
    name: str = "Attestation d'affiliation"
    description: list[str] = [
        "Document officiel attestant de l'affiliation d'une structure à un organisme d'affiliation",
        "Contient les informations de la structure affiliée : nom, président, adresse, numéro SIRET",
        "Contient les informations de l'organisme d'affiliation : nom, adresse, téléphone, email",
        "Date d'émission du document",
        "Période de validité de l'attestation (date de début et date de fin)",
        "Document généralement émis par une fédération, une association ou un organisme officiel",
    ]
    document_model: Type[AttestationAffiliationModel] = AttestationAffiliationModel

