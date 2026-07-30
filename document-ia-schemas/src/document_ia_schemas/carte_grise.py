from datetime import date
from typing import Optional, Type

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric
from document_ia_schemas.identity import Identity


class CarteGriseModel(BaseModel):
    numero_immatriculation: Optional[str] = Field(
        default=None,
        description="Numéro d'immatriculation du véhicule (Rubrique A, ex: 'AA-123-AA' ou '1234 AB 75').",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    date_premiere_immatriculation: FuzzyDate = Field(
        default=None,
        description="Date de première immatriculation ou première mise en circulation du véhicule (Rubrique B, format JJ/MM/AAAA). Si absente, renseigner `null`.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    date_certificat: FuzzyDate = Field(
        default=None,
        description="Date d'émission ou de délivrance du présent certificat d'immatriculation (Rubrique I, format JJ/MM/AAAA). Si absente, renseigner `null`.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    numero_formule: Optional[str] = Field(
        default=None,
        description="Numéro de formule du certificat d'immatriculation (format alphanumérique à 11 caractères, ex: '2021AB12345').",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    identite_titulaire: Identity = Field(
        default=None,
        description="Nom de famille et prénom du titulaire principal ou raison sociale du titulaire principal du certificat (Rubrique C.1 / C.4.1).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    adresse_titulaire: Optional[str] = Field(
        default=None,
        description="Adresse complète de résidence du titulaire (Rubrique C.3).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    cotitulaire: Identity = Field(
        default=None,
        description="Nom et prénom du ou des cotitulaires (Rubrique C.4.1 si présent). Si absent, renseigner `null`.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    marque: Optional[str] = Field(
        default=None,
        description="Marque du véhicule (Rubrique D.1, ex: RENAULT, PEUGEOT, CITROEN).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    type_variante_version: Optional[str] = Field(
        default=None,
        description="Type, variante, version (TVV) du véhicule (Rubrique D.2).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    denomination_commerciale: Optional[str] = Field(
        default=None,
        description="Dénomination commerciale du véhicule (Rubrique D.3, ex: CLIO, 208, GOLF).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    numero_serie_vin: Optional[str] = Field(
        default=None,
        description="Numéro d'identification du véhicule / VIN (17 caractères alphanumériques, Rubrique E).",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    genre_national: Optional[str] = Field(
        default=None,
        description="Genre national du véhicule (Rubrique J.1, ex: VP, CTTE, MTL, MOTO, CYCL, TRA).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    carrosserie_national: Optional[str] = Field(
        default=None,
        description="Carrosserie nationale du véhicule (Rubrique J.3, ex: CI, BREAK, DERIV VP, COUPE, CABR).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    source_energie: Optional[str] = Field(
        default=None,
        description="Source d'énergie / carburant du véhicule (Rubrique P.3, ex: ES, GO, EH, EL, GL, GA).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    puissance_administrative: Optional[float] = Field(
        default=None,
        description="Puissance administrative nationale en chevaux fiscaux (CV) (Rubrique P.6).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    puissance_net_max: Optional[float] = Field(
        default=None,
        description="Puissance nette maximale en kW (Rubrique P.2).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    cylindree: Optional[int] = Field(
        default=None,
        description="Cylindrée du moteur en cm³ (Rubrique P.1).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    places_assises: Optional[int] = Field(
        default=None,
        description="Nombre de places assises y compris le conducteur (Rubrique S.1).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    masse_en_service: Optional[int] = Field(
        default=None,
        description="Masse du véhicule en service avec carrosserie / poids à vide en kg (Rubrique G.1 ou G).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    ptac: Optional[int] = Field(
        default=None,
        description="Masse maximale techniquement admissible / PTAC en kg (Rubrique F.2 ou F.1).",
        json_schema_extra={"metrics": Metric.COMPARE_NUMBER},
    )
    date_echeance_controle_technique: FuzzyDate = Field(
        default=None,
        description="Date limite de validité du contrôle technique (Rubrique X.1 si présente, format JJ/MM/AAAA). Si absente, renseigner `null`.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )


class CarteGriseExtractSchema(BaseDocumentTypeSchema[CarteGriseModel]):
    type: str = "carte_grise"
    name: str = "Carte grise (Certificat d'immatriculation)"
    description: list[str] = [
        "Document officiel français (Certificat d'immatriculation / Carte grise)",
        'Contient des mentions comme "République Française", "Certificat d\'immatriculation" ou "Union Européenne"',
        "Présence de rubriques alphabétiques officielles (A, B, C.1, C.3, D.1, D.2, D.3, E, F.2, G.1, J.1, P.3, P.6, S.1, X.1)",
        "Numéro d'immatriculation (format SIV AA-123-AA ou FNI 1234 AB 75)",
        "Titulaire principal, cotitulaire et adresse de résidence",
        "Numéro d'identification du véhicule (VIN à 17 caractères)",
        "Caractéristiques techniques : marque, dénomination commerciale, genre national (VP, CTTE...), énergie (ES, GO, EL...), puissance fiscale (P.6)",
        "Numéro de formule du certificat d'immatriculation (ex: 2021AB12345)",
    ]
    examples: list[CarteGriseModel] = [
        CarteGriseModel(
            numero_immatriculation="AA-123-AA",
            date_premiere_immatriculation=date(2018, 5, 12),
            date_certificat=date(2021, 9, 20),
            numero_formule="2021AB12345",
            identite_titulaire="DUPONT JEAN",
            adresse_titulaire="12 RUE DE LA PAIX 75002 PARIS",
            cotitulaire=None,
            marque="RENAULT",
            type_variante_version="B8MA00",
            denomination_commerciale="CLIO",
            numero_serie_vin="VF1B8MA0012345678",
            genre_national="VP",
            carrosserie_national="CI",
            source_energie="ES",
            puissance_administrative=5.0,
            puissance_net_max=66.0,
            cylindree=898,
            places_assises=5,
            masse_en_service=1165,
            ptac=1600,
            date_echeance_controle_technique=date(2025, 5, 12),
        )
    ]

    document_model: Type[CarteGriseModel] = CarteGriseModel
