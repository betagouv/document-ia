from document_ia_schemas import resolve_extract_schema


def _contains_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


def test_quittance_loyer_json_schema_contains_main_fields_and_strips_metrics():
    schema = resolve_extract_schema("quittance_loyer")
    js = schema.get_json_schema_dict()

    assert isinstance(js, dict)
    assert js.get("type") == "object"

    props = js.get("properties", {})
    assert "nature_document" in props
    assert "bailleur" in props
    assert "locataires" in props
    assert "periode_debut" in props
    assert "periode_fin" in props
    assert "loyer_de_base" in props
    assert "provisions_charges" in props
    assert "montant_total_acquitte" in props

    assert not _contains_key(js, "metrics")
