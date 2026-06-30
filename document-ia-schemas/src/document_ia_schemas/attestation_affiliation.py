from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema


class AttestationAffiliationModel(BaseModel):
    # Informations de l'affilié
    nom_structure: Optional[str] = Field(
        default=None,
        description="Nom de la structure affiliée",
    )
    adresse_siege_structure: Optional[str] = Field(
        default=None,
        description="Adresse complète du siège social de la structure affiliée",
    )
    numero_siret_structure: Optional[str] = Field(
        default=None,
        description="Numéro SIRET de la structure affiliée (14 chiffres)",
    )
    # Informations de l'organisme d'affiliation
    nom_organisme: Optional[str] = Field(
        default=None,
        description="Nom de l'organisme d'affiliation",
    )
    adresse_siege_organisme: Optional[str] = Field(
        default=None,
        description="Adresse complète du siège social de l'organisme d'affiliation",
    )
    nom_president_organisme: Optional[str] = Field(
        default=None,
        description="Nom du président de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
    )
    telephone_organisme: Optional[str] = Field(
        default=None,
        description="Numéro de téléphone de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
    )
    email_organisme: Optional[str] = Field(
        default=None,
        description="Adresse email de l'organisme d'affiliation (si existant). Si absente, renseigner `null`.",
    )
    # Date d'émission
    date_emission: Optional[str] = Field(
        default=None,
        description="Date d'émission du document (format JJ/MM/AAAA)",
    )
    # Période de validité
    date_debut_validite: Optional[str] = Field(
        default=None,
        description="Date de début de validité de l'attestation (format JJ/MM/AAAA). Si absente, renseigner `null`.",
    )
    date_fin_validite: Optional[str] = Field(
        default=None,
        description="Date de fin de validité de l'attestation (format JJ/MM/AAAA). Si absente, renseigner `null`.",
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
    examples: list[AttestationAffiliationModel] = [
        AttestationAffiliationModel(
            nom_structure="Association Sportive de Paris",
            adresse_siege_structure="123 Rue de la République, 75001 Paris",
            numero_siret_structure="12345678901234",
            nom_organisme="Fédération Française de Sport",
            adresse_siege_organisme="456 Avenue des Sports, 75012 Paris",
            nom_president_organisme="MARTIN Jean",
            telephone_organisme="01 23 45 67 89",
            email_organisme="contact@federation-sport.fr",
            date_emission="2024-03-15",
            date_debut_validite="2024-01-01",
            date_fin_validite="2024-12-31",
        ),
        AttestationAffiliationModel(
            nom_structure="Club Athlétique de Lyon",
            adresse_siege_structure="22 Avenue Victor Hugo, 69003 Lyon",
            numero_siret_structure="98765432109876",
            nom_organisme="Ligue Rhône-Alpes de Football",
            adresse_siege_organisme="10 Rue de la Part-Dieu, 69003 Lyon",
            nom_president_organisme=None,
            telephone_organisme=None,
            email_organisme="contact@ligue-rhone-alpes.fr",
            date_emission="2024-06-01",
            date_debut_validite="2024-06-01",
            date_fin_validite=None,
        ),
    ]
    document_model: Type[AttestationAffiliationModel] = AttestationAffiliationModel

