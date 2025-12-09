from typing import Set

from document_ia_schemas import resolve_extract_schema


def _extract_types(prop_schema) -> Set[str]:
    # Récupère les types JSON Schema déclarés pour un champ (gère type, anyOf, oneOf)
    types = set()
    if isinstance(prop_schema, dict):
        t = prop_schema.get("type")
        if isinstance(t, str):
            types.add(t)
        elif isinstance(t, list):
            types.update([x for x in t if isinstance(x, str)])
        for key in ("anyOf", "oneOf", "allOf"):
            if key in prop_schema and isinstance(prop_schema[key], list):
                for sub in prop_schema[key]:
                    if isinstance(sub, dict) and "type" in sub:
                        st = sub["type"]
                        if isinstance(st, str):
                            types.add(st)
                        elif isinstance(st, list):
                            types.update([x for x in st if isinstance(x, str)])
    return types


essential_fields = {
    "annee_revenus",
    "date_mise_en_recouvrement",
    "declarant_1_identite",
    "declarant_1_nom_naissance",
    "declarant_1_numero_fiscal",
    "declarant_2_identite",
    "declarant_2_nom_naissance",
    "declarant_2_numero_fiscal",
    "reference_avis",
    "nombre_parts",
    "revenu_fiscal_reference",
    "revenu_brut_global",
    "revenu_imposable",
    "impot_revenu_net_avant_corrections",
    "montant_impot",
}


def test_json_schema_keys_exact_and_no_alias():
    schema = resolve_extract_schema("avis_imposition")
    js = schema.get_json_schema_dict()

    # Structure de base
    assert isinstance(js, dict)
    assert js.get("type") == "object"
    assert "properties" in js and isinstance(js["properties"], dict)

    props = js["properties"]

    # Les clés doivent être EXACTEMENT les noms des variables (pas les alias)
    assert set(props.keys()) == essential_fields

    # Vérifier que certains alias connus n'apparaissent PAS comme clés
    forbidden_aliases = {
        "Référence d'avis d'impôt",
        "Année des revenus",
        "Nom et Prénom du déclarant 1",
        "Nom de naissance du déclarant 1",
        "Numéro fiscal du déclarant 1",
        "Nom et Prénom du déclarant 2",
        "Nom de naissance du déclarant 2",
        "Revenu fiscal de référence",
        "Date de mise en recouvrement",
    }
    assert forbidden_aliases.isdisjoint(set(props.keys()))


def test_json_schema_required_and_types():
    schema = resolve_extract_schema("avis_imposition")
    js = schema.get_json_schema_dict()

    props = js["properties"]

    # Champs requis: variables (non Optional) du modèle
    required = set(js.get("required", []))
    expected_required = {
        "annee_revenus",
        "declarant_1_identite",
        "declarant_1_nom_naissance",
        "declarant_2_identite",
        "declarant_2_nom_naissance",
        "revenu_fiscal_reference"
    }
    assert required == expected_required

    # Vérifier quelques types clés
    # annee_revenus -> string
    assert "string" in _extract_types(props["annee_revenus"])

    # revenu_fiscal_reference -> number
    assert "number" in _extract_types(props["revenu_fiscal_reference"])

    # nombre_parts -> number (optionnel: peut être anyOf [number, null])
    assert "number" in _extract_types(props["nombre_parts"])


def _contains_key(obj, key: str) -> bool:
    """Retourne True si la clé existe quelque part dans la structure (dict/list)."""
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


def test_json_schema_strips_metrics_extra():
    """Vérifie que les clés issues de json_schema_extra (ex: "metrics") sont exclues."""
    schema = resolve_extract_schema("avis_imposition")
    js = schema.get_json_schema_dict()

    assert not _contains_key(js, "metrics"), "La clé 'metrics' ne doit pas apparaître dans le JSON Schema"
