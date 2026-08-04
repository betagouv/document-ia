from typing import Type, Optional, List
from datetime import date

from pydantic import BaseModel, Field

from document_ia_schemas import BaseDocumentTypeSchema
from document_ia_schemas.base_document_type_schema import FuzzyDate
from document_ia_schemas.field_metrics import Metric


class QualificationModel(BaseModel):
    """Lignes de la rubrique XII (1 ligne = 1 qualification).
    Parfois manuscrite. Tous les champs sont optionnels et la liste peut être vide si la section n'est pas lisible.
    """

    libelle: Optional[str] = Field(
        default=None,
        description="Intitulé de la qualification (rubrique XII, colonne 'Qualifications/Ratings').",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_epreuve: FuzzyDate = Field(
        default=None,
        description="Date de l'épreuve (Date of test). Si absente ou illisible, renseigner `null`.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    valide_jusqu_au: FuzzyDate = Field(
        default=None,
        description="Date de fin de validité de la qualification (Valid until). Si absente, renseigner `null`.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    numero_examinateur: Optional[str] = Field(
        default=None,
        description="Numéro d'autorisation de l'examinateur (Examiner authorisation n°). Si absente, renseigner `null`.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class LicencePilotePartFCLModel(BaseModel):
    """Licence de membre d'équipage de conduite (EASA Form 141 / Part-FCL / Part-SFCL).
    Modèle normalisé européen standardisé selon Appendix I to ANNEX VI (Part-ARA) du réglement (EU) 1178/2011.
    """

    # --- Rubrique I : État d'émission ---
    etat_emission: Optional[str] = Field(
        default=None,
        description="Rubrique I = État d'émission du document / State of issue. Pays émetteur en clair.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    code_pays: Optional[str] = Field(
        default=None,
        description="Code pays ISO de l'autorité émettrice (trouvé en fin de rubrique II).",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )

    # --- Rubrique III : Numéro de licence ---
    numero_licence: Optional[str] = Field(
        default=None,
        description=(
            "Rubrique III = Numéro de la licence / Licence number."
            "Commence toujours par le code pays, suivi de 'FCL.', 'BFCL.' ou 'SFCL.' selon le cas, puis d'un code alphanumérique."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique II : intitulé + date de délivrance initiale ---
    type_licence: Optional[str] = Field(
        default=None,
        description=(
            "Rubrique II = Sigle du type de licence figurant dans l'intitulé. "
            "Valeurs possibles : LAPL (pilote d'aéronef léger), PPL (pilote privé), "
            "SPL (pilote de planeur), BPL (pilote de ballon), CPL (pilote professionnel), "
            "MPL (équipage multiple), ATPL (pilote de ligne). Extraire uniquement le sigle."
        ),
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    categorie_aeronef: Optional[str] = Field(
        default=None,
        description="Catégorie d'aéronef accolée au type de licence, entre parenthèses dans l'intitulé pour les licences avion et hélicoptère. Ex pour 'CPL(A)' -> 'A'. Pour les licences SPL c'est toujours 'S' et pour les licences BPL c'est toujours 'B'.",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    date_delivrance_initiale: FuzzyDate = Field(
        default=None,
        description="Rubrique II = Date de la délivrance initiale / date of initial issue.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    reglementation: Optional[str] = Field(
        default=None,
        description="Référentiel réglementaire mentionné ('Délivrée conformément à la Part-FCL', 'Part-BFCL' pour les ballons, ou 'Part-SFCL' pour les planeurs). Valeurs: 'Part-FCL', 'Part-BFCL' ou 'Part-SFCL'. Se déduit aussi du préfixe du numéro de licence.",
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    version_formulaire: Optional[str] = Field(
        default=None,
        description=(
            "Version du formulaire EASA mentionnée en bas de la page de couverture. "
            "'EASA Form 141 Issue 2' ou 'EASA Form 141 Issue 3', y compris ses "
            "variantes linguistiques ('EASA Formblatt 141 Ausgabe 2', 'Modulo 141 AESA Edizione 2'). "
            "Extraire le numéro d'issue."
        ),
        json_schema_extra={"metrics": Metric.EQUALITY},
    )

    # --- Rubrique IV / IVa / XIV : identité du titulaire ---
    nom: Optional[str] = Field(
        default=None,
        description="Rubrique IV = Nom de famille du titulaire (Last name of holder). En majuscules sur le document.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    prenom: Optional[str] = Field(
        default=None,
        description="Rubrique IV = Prénom(s) du titulaire (first name of holder).",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_naissance: FuzzyDate = Field(
        default=None,
        description="Rubrique IVa = Date de naissance du titulaire / Date of birth.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Rubrique XIV = Lieu de naissance du titulaire / Place of birth.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    nationalite: Optional[str] = Field(
        default=None,
        description="Rubrique VI = Nationalité du titulaire / Nationality.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique VIII / X / XI : autorité et émission ---
    autorite_emission: Optional[str] = Field(
        default=None,
        description="Rubrique VIII = Service d'émission / Issuing authority.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_emission: FuzzyDate = Field(
        default=None,
        description="Rubrique X = Date d'émission du présent document / date of issue.",
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )

    # --- Rubrique XII : privilèges de radiotéléphonie ---
    radiotelephonie: Optional[str] = Field(
        default=None,
        description=(
            "Rubrique XII = Privilèges de radiotéléphonie / Radiotelephony privileges. "
            "Le titulaire a démontré sa compétence R/T dans la/les langue(s) indiquée(s). "
            "Reporter la/les langue(s) mentionnée(s). Peut figurer sur la licence ou sur un certificat séparé (dans ce cas, `null`)."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique XIII : compétences linguistiques ---
    competences_linguistiques: Optional[str] = Field(
        default=None,
        description="Rubrique XIII (Remarques) = Compétences linguistiques / Language Proficiency. Reporter langue + niveau + éventuelle date.",
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique XII : qualifications / ratings (best-effort) ---
    qualifications: List[QualificationModel] = Field(
        default_factory=list,
        description=(
            "Rubrique XII = Liste des qualifications / ratings. "
            "Extraction best-effort : ce tableau est fréquemment manuscrit et peut être vide. Si non lisible, renvoyer une liste vide []."
        ),
        json_schema_extra={"metrics": Metric.SKIP},
    )

    # --- Conformité OACI (mention présente sur le document) ---
    mention_conformite_oaci: Optional[str] = Field(
        default=None,
        description=(
            "Phrase de conformité OACI/ICAO figurant sur la page de couverture, reportée VERBATIM (telle quelle), sans l'interpréter."
        ),
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class LicencePilotePartFCLExtractSchema(
    BaseDocumentTypeSchema[LicencePilotePartFCLModel]
):
    type: str = "licence_navigant_fcl"
    name: str = "Licence de membre d'équipage de conduite (EASA Form 141)"
    description: list[str] = [
        "Licence de pilote européenne au format normalisé EASA Form 141 (Part-FCL, Part-SFCL ou Part-BFCL)",
        "Mentions 'LICENCE DE MEMBRE D'EQUIPAGE DE CONDUITE' / 'FLIGHT CREW LICENCE' / 'PILOTENLIZENZ' / 'LICENZA D'EQUIPAGGIO DI CONDOTTA' ou similaire",
        "Structuré en rubriques numérotées en chiffres romains (I, II, III, IV, IVa, V, VI, VII, VIII, IX, X, XI, XII, XIII, XIV)",
        "Couvre les types LAPL, PPL, SPL, BPL, CPL, MPL, ATPL",
        "Émis par une autorité de l'aviation civile d'un État membre (DGAC/DSAC France, Luftfahrt-Bundesamt Allemagne, ENAC Italie...)",
        "Peut être rédigé dans la langue nationale + anglais",
        "Contient un tableau de qualifications (rubrique XII), parfois manuscrit",
    ]
    examples: list[LicencePilotePartFCLModel] = [
        LicencePilotePartFCLModel(
            etat_emission="FRANCE",
            code_pays="FRA",
            numero_licence="FRA.FCL.CA12345678",
            type_licence="CPL",
            categorie_aeronef="A",
            date_delivrance_initiale=date(2014, 2, 17),
            reglementation="Part-FCL",
            version_formulaire="Issue 2",
            nom="DUPONT",
            prenom="JEAN",
            date_naissance=date(1990, 1, 1),
            lieu_naissance="LYON",
            nationalite="Française",
            autorite_emission="DSAC Centre-Est",
            date_emission=date(2026, 3, 23),
            radiotelephonie="français et anglais",
            competences_linguistiques="Français VFR niveau 6, Anglais niveau 4 jusqu'au 31/10/2027",
            qualifications=[
                QualificationModel(
                    libelle="SEP terrestre",
                    date_epreuve=date(2025, 5, 20),
                    valide_jusqu_au=date(2027, 7, 31),
                    numero_examinateur="F-CREA12345678",
                ),
            ],
            mention_conformite_oaci=(
                "This licence complies with ICAO standards, except for the LAPL and BIR privileges"
            ),
        ),
        LicencePilotePartFCLModel(
            etat_emission="DEUTSCHLAND",
            code_pays="DE",
            numero_licence="DE.FCL1234",
            type_licence="MPL",
            categorie_aeronef="A",
            date_delivrance_initiale=date(2018, 5, 12),
            reglementation="Part-FCL",
            version_formulaire="Issue 1",
            nom="MÜLLER",
            prenom="HANS",
            date_naissance=date(1985, 4, 15),
            lieu_naissance="BERLIN",
            nationalite="Allemande",
            autorite_emission="Luftfahrt-Bundesamt",
            date_emission=date(2024, 1, 10),
            radiotelephonie="German or English",
            competences_linguistiques="Englisch/English Level 4 bis/until 19.03.2021",
            qualifications=[
                QualificationModel(
                    libelle="A320",
                    date_epreuve=date(2023, 3, 15),
                    valide_jusqu_au=date(2025, 3, 31),
                    numero_examinateur="E-TRE-12345",
                ),
            ],
            mention_conformite_oaci=None,
        ),
        LicencePilotePartFCLModel(
            etat_emission="ITALIA",
            code_pays="IT",
            numero_licence="IT.FCL.1234",
            type_licence="SPL",
            categorie_aeronef="S",
            date_delivrance_initiale=date(2020, 9, 1),
            reglementation="Part-SFCL",
            version_formulaire="Issue 2",
            nom="ROSSI",
            prenom="MARCO",
            date_naissance=date(1992, 8, 20),
            lieu_naissance="ROMA",
            nationalite="Croatian",
            autorite_emission="ENAC",
            date_emission=date(2023, 6, 1),
            radiotelephonie="français",
            competences_linguistiques="Français VFR niveau 6",
            qualifications=[
                QualificationModel(
                    libelle="DHC8",
                    date_epreuve=date(2022, 6, 10),
                    valide_jusqu_au=date(2024, 6, 30),
                    numero_examinateur="IT.FCL.1234",
                ),
                QualificationModel(
                    libelle="ATR 42/72",
                    date_epreuve=date(2021, 4, 5),
                    valide_jusqu_au=date(2023, 4, 30),
                    numero_examinateur="BE.FCL.132456",
                ),
            ],
            mention_conformite_oaci=None,
        ),
    ]
    document_model: Type[LicencePilotePartFCLModel] = LicencePilotePartFCLModel
