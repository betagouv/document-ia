from typing import Type, Optional, List

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
        examples=["A320", "SEP terrestre", "DHC8", "ATR 42/72"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_epreuve: FuzzyDate = Field(
        default=None,
        description="Date de l'épreuve (Date of test). Si absente ou illisible, renseigner `null`.",
        examples=["2025-05-20"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    valide_jusqu_au: FuzzyDate = Field(
        default=None,
        description="Date de fin de validité de la qualification (Valid until). Si absente, renseigner `null`.",
        examples=["2027-07-31"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    numero_examinateur: Optional[str] = Field(
        default=None,
        description="Numéro d'autorisation de l'examinateur (Examiner authorisation n°). Si absente, renseigner `null`.",
        examples=["F-CREA12345678", "IT.FCL.1234",
                  "E-TRE-12345", "BE.FCL.132456"],
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
        examples=["FRANCE", "DEUTSCHLAND", "ITALIA"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    code_pays: Optional[str] = Field(
        default=None,
        description="Code pays ISO de l'autorité émettrice (trouvé en fin de rubrique II).",
        examples=["FRA", "IT"],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )

    # --- Rubrique III : Numéro de licence ---
    numero_licence: Optional[str] = Field(
        default=None,
        description=(
            "Rubrique III = Numéro de la licence / Licence number."
            "Commence toujours par le code pays, suivi de 'FCL.', 'BFCL.' ou 'SFCL.' selon le cas, puis d'un code alphanumérique."
        ),
        examples=["FRA.FCL.CA12345678", "FRA.SFCL.PS12345678", "DE.FCL1234"],
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
        examples=["CPL", "SPL", "MPL"],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    categorie_aeronef: Optional[str] = Field(
        default=None,
        description="Catégorie d'aéronef accolée au type de licence, entre parenthèses dans l'intitulé pour les licences avion et hélicoptère. Ex pour 'CPL(A)' -> 'A'. Pour les licences SPL c'est toujours 'S' et pour les licences BPL c'est toujours 'B'.",
        examples=["A", "S", "H"],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )
    date_delivrance_initiale: FuzzyDate = Field(
        default=None,
        description="Rubrique II = Date de la délivrance initiale / date of initial issue.",
        examples=["2014-02-17"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    reglementation: Optional[str] = Field(
        default=None,
        description="Référentiel réglementaire mentionné ('Délivrée conformément à la Part-FCL', 'Part-BFCL' pour les ballons, ou 'Part-SFCL' pour les planeurs). Valeurs: 'Part-FCL', 'Part-BFCL' ou 'Part-SFCL'. Se déduit aussi du préfixe du numéro de licence.",
        examples=["Part-FCL"],
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
        examples=["Issue 1", "Issue 2"],
        json_schema_extra={"metrics": Metric.EQUALITY},
    )

    # --- Rubrique IV / IVa / XIV : identité du titulaire ---
    nom: Optional[str] = Field(
        default=None,
        description="Rubrique IV = Nom de famille du titulaire (Last name of holder). En majuscules sur le document.",
        examples=["DUPONT"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    prenom: Optional[str] = Field(
        default=None,
        description="Rubrique IV = Prénom(s) du titulaire (first name of holder).",
        examples=["JEAN"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_naissance: FuzzyDate = Field(
        default=None,
        description="Rubrique IVa = Date de naissance du titulaire / Date of birth.",
        examples=["1990-01-01"],
        json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY},
    )
    lieu_naissance: Optional[str] = Field(
        default=None,
        description="Rubrique XIV = Lieu de naissance du titulaire / Place of birth.",
        examples=["LYON"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    nationalite: Optional[str] = Field(
        default=None,
        description="Rubrique VI = Nationalité du titulaire / Nationality.",
        examples=["Française", "Croatian"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique VIII / X / XI : autorité et émission ---
    autorite_emission: Optional[str] = Field(
        default=None,
        description="Rubrique VIII = Service d'émission / Issuing authority.",
        examples=["DSAC Centre-Est", "DSAC Nord-Est",
                  "D.Ile de France", "Luftfahrt-Bundesamt", "ENAC"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )
    date_emission: FuzzyDate = Field(
        default=None,
        description="Rubrique X = Date d'émission du présent document / date of issue.",
        examples=["2026-03-23"],
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
        examples=["français et anglais", "français", "German or English"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique XIII : compétences linguistiques ---
    competences_linguistiques: Optional[str] = Field(
        default=None,
        description="Rubrique XIII (Remarques) = Compétences linguistiques / Language Proficiency. Reporter langue + niveau + éventuelle date.",
        examples=["Français VFR niveau 6", "Anglais niveau 4 jusqu'au 31/10/2027",
                  "Englisch/English Level 4 bis/until 19.03.2021"],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )

    # --- Rubrique XII : qualifications / ratings (best-effort) ---
    qualifications: List[QualificationModel] = Field(
        default_factory=list,
        description=(
            "Rubrique XII = Liste des qualifications / ratings. "
            "Extraction best-effort : ce tableau est fréquemment manuscrit et peut être vide. Si non lisible, renvoyer une liste vide []. "
        ),
        json_schema_extra={"metrics": Metric.SKIP},
    )

    # --- Conformité OACI (mention présente sur le document) ---
    mention_conformite_oaci: Optional[str] = Field(
        default=None,
        description=(
            "Phrase de conformité OACI/ICAO figurant sur la page de couverture, reportée VERBATIM (telle quelle), sans l'interpréter."
        ),
        examples=[
            "This licence complies with ICAO standards, except for the LAPL and BIR privileges"
        ],
        json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE},
    )


class LicencePilotePartFCLExtractSchema(
    BaseDocumentTypeSchema[LicencePilotePartFCLModel]
):
    type: str = "licence_equipage_conduite"
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
            numero_licence="FRA.FCL.CA87654321",
            type_licence="CPL",
            categorie_aeronef="A",
            date_delivrance_initiale="2024-06-26",
            reglementation="Part-FCL",
            version_formulaire="Issue 2",
            nom="DUPONT",
            prenom="JEAN",
            date_naissance="1990-01-01",
            lieu_naissance="PARIS",
            nationalite="Française",
            autorite_emission="D.Ile de France",
            date_emission="2026-03-23",
            radiotelephonie="français et anglais",
            competences_linguistiques="Français VFR niveau 6, Anglais niveau 4 jusqu'au 31/10/2027",
            qualifications=[
                QualificationModel(
                    libelle="MEP",
                    date_epreuve="2025-05-20",
                    valide_jusqu_au="2026-05-31",
                    numero_examinateur="F-CREA00223344",
                ),
                QualificationModel(
                    libelle="SEP terrestre",
                    date_epreuve=None,
                    valide_jusqu_au="2027-07-31",
                    numero_examinateur=None,
                ),
            ],
            mention_conformite_oaci=(
                "This licence complies with ICAO standards, except for the LAPL and BIR privileges"
            ),
        )
    ]
    document_model: Type[LicencePilotePartFCLModel] = LicencePilotePartFCLModel
