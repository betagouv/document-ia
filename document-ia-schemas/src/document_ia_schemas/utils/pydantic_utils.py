from typing import Any, cast


def _get_ref_name(ref_raw: Any) -> str:
    # Extract the definition name from a JSON Schema $ref string.
    return str(ref_raw).split("/")[-1]


def _get_sub_properties(defs: dict[str, Any], ref_raw: Any) -> dict[str, Any]:
    # Resolve a $ref into its target definition properties.
    ref_name = _get_ref_name(ref_raw)
    sub_def_raw: Any = defs.get(ref_name, {})
    sub_def = cast(dict[str, Any], sub_def_raw)
    sub_props_raw: Any = sub_def.get("properties", {})
    return cast(dict[str, Any], sub_props_raw)


def _get_ref_properties_from_dict(
        value_dict: dict[str, Any],
        defs: dict[str, Any]
) -> dict[str, Any] | None:
    # Return referenced properties when the current node is a $ref.
    if "$ref" not in value_dict:
        return None
    return _get_sub_properties(defs, value_dict["$ref"])


def _get_array_ref_properties(
        value_dict: dict[str, Any],
        defs: dict[str, Any]
) -> dict[str, Any] | None:
    # Resolve referenced item properties when the field is a list of models.
    if value_dict.get("type") != "array" or "items" not in value_dict:
        return None
    items_raw: Any = value_dict["items"]
    if not isinstance(items_raw, dict):
        return None
    items_dict = cast(dict[str, Any], items_raw)
    if "$ref" not in items_dict:
        return None
    return _get_sub_properties(defs, items_dict["$ref"])


def extract_fields_info(
        properties: dict[str, Any],
        defs: dict[str, Any],
        level: int = 0
) -> list[dict[str, Any]]:
    # Flatten nested schema properties into a labeled list with nesting level.
    fields: list[dict[str, Any]] = []

    for key, val in properties.items():
        if not isinstance(val, dict):
            continue

        value_dict: dict[str, Any] = cast(dict[str, Any], val)
        raw_desc: Any = value_dict.get("description", "")
        desc: str = str(raw_desc) if raw_desc is not None else ""

        array_ref_props = _get_array_ref_properties(value_dict, defs)
        if array_ref_props is not None:
            fields.append({"name": f"{key} (Liste)", "description": desc, "level": level})
            fields.extend(extract_fields_info(array_ref_props, defs, level + 1))
            continue

        ref_props = _get_ref_properties_from_dict(value_dict, defs)
        if ref_props is not None:
            fields.append({"name": f"{key} (Objet)", "description": desc, "level": level})
            fields.extend(extract_fields_info(ref_props, defs, level + 1))
            continue

        fields.append({"name": key, "description": desc, "level": level})

    return fields


def build_response_format(
        properties: dict[str, Any],
        defs: dict[str, Any]
) -> dict[str, Any]:
    """
    Build the expected JSON response format by resolving nested models and lists.
    """
    result: dict[str, Any] = {}

    for key, val in properties.items():
        if not isinstance(val, dict):
            result[key] = "string"
            continue

        value_dict = cast(dict[str, Any], val)
        raw_type: Any = value_dict.get("type", "string")
        field_type: str = str(raw_type) if raw_type is not None else "string"

        array_ref_props = _get_array_ref_properties(value_dict, defs)
        if array_ref_props is not None:
            result[key] = [build_response_format(array_ref_props, defs)]
            continue

        if field_type == "array" and "items" in value_dict:
            items_raw: Any = value_dict["items"]
            if isinstance(items_raw, dict):
                items_dict = cast(dict[str, Any], items_raw)
                item_raw_type: Any = items_dict.get("type", "string")
                item_type: str = str(item_raw_type) if item_raw_type is not None else "string"
                result[key] = [item_type]
            else:
                result[key] = ["string"]
            continue

        ref_props = _get_ref_properties_from_dict(value_dict, defs)
        if ref_props is not None:
            result[key] = build_response_format(ref_props, defs)
            continue

        result[key] = field_type

    return result
