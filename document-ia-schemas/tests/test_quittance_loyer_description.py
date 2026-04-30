from document_ia_schemas import resolve_extract_schema


def test_quittance_loyer_description_dict_keys_only_type_name_description():
    schema = resolve_extract_schema("quittance_loyer")
    desc = schema.get_document_description_dict()

    assert isinstance(desc, dict)
    assert set(desc.keys()) == {"type", "name", "description"}
    assert desc["type"] == "quittance_loyer"
    assert desc["name"] == "Quittance de loyer"
    assert isinstance(desc["description"], list)
