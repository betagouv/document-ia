from document_ia_schemas import resolve_extract_schema


def test_description_dict_keys_only_type_name_description():
    schema = resolve_extract_schema("avis_imposition")
    desc = schema.get_document_description_dict()

    assert isinstance(desc, dict), "Le résultat doit être un dict"

    expected_keys = {"type", "name", "description"}
    assert set(desc.keys()) == expected_keys, (
        f"Les clés doivent être exactement {expected_keys}, trouvées: {set(desc.keys())}"
    )

    # Vérifie les valeurs de base
    assert desc["type"] == schema.type
    assert desc["name"] == schema.name


def test_description_dict_value_types():
    schema = resolve_extract_schema("avis_imposition")
    desc = schema.get_document_description_dict()

    # Types attendus
    assert isinstance(desc["type"], str)
    assert isinstance(desc["name"], str)
    assert isinstance(desc["description"], list)

    # Si non vide, tous les éléments de description doivent être des str
    if desc["description"]:
        assert all(isinstance(x, str) for x in desc["description"])
