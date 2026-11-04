from datetime import date, datetime
from decimal import Decimal
from typing import (
    Any,
    Literal,
    Optional,
    Union,
    get_args,
    get_origin,
    Dict,
    cast,
    Annotated,
)

from pydantic import BaseModel, Field
from document_ia_schemas.base_document_type_schema import InvalidProperty


class GenericProperty(BaseModel):
    name: str
    value: Union[
        str,
        int,
        float,
        bool,
        list["GenericProperty"],
        list[str],
        list[int],
        list[float],
        list[bool],
        None,
    ] = Field(
        json_schema_extra={"x-mask": True},
    )
    type: Literal["string", "number", "boolean", "object", "date", "list"]
    anomaly: Optional[InvalidProperty] = Field(
        default=None,
        exclude_if=lambda v: v is None,
        json_schema_extra={"x-mask": True},
    )

    @classmethod
    def _is_invalid_property_compatible(cls, annotation: Any) -> bool:
        """Check if the given annotation allows an InvalidProperty."""
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if args:
                annotation = args[0]

        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is Union:
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, InvalidProperty):
                    return True
        elif isinstance(annotation, type) and issubclass(annotation, InvalidProperty):
            return True

        return False

    @classmethod
    def convert_pydantic_model(
        cls, model: Optional[BaseModel]
    ) -> list["GenericProperty"]:
        properties: list["GenericProperty"] = []
        if model is None:
            return properties

        model_fields = getattr(type(model), "model_fields", {})

        for field_name, field_value in model:
            # Resolve the field annotation to decide the UI type.
            field_info = model_fields.get(field_name)
            annotation: Any = (  # pyright: ignore [reportUnknownVariableType]
                field_info.annotation
                if field_info and field_info.annotation is not None
                else type(field_value)
            )

            # Check if this property type is compatible with InvalidProperty
            is_anomaly_compatible = cls._is_invalid_property_compatible(annotation)

            # Infer the UI type from annotation and runtime value.
            ui_type = cls._infer_ui_type(annotation, field_value)
            final_value: Any = field_value
            anomaly: Optional[InvalidProperty] = None

            # Normalize the value based on its runtime type and anomaly compatibility.
            if isinstance(field_value, InvalidProperty):
                final_value = None
                anomaly = field_value
            elif (
                is_anomaly_compatible
                and isinstance(field_value, dict)
                and "code" in field_value
                and "raw_value" in field_value
            ):
                try:
                    anomaly = InvalidProperty.model_validate(field_value)
                    final_value = None
                except Exception:
                    pass
            elif isinstance(field_value, BaseModel):
                final_value = cls.convert_pydantic_model(field_value)
                ui_type = "object"
            elif (
                isinstance(field_value, list)
                and field_value
                and isinstance(field_value[0], BaseModel)
            ):
                model_items = cast(list[BaseModel], field_value)
                final_value = [
                    GenericProperty(
                        name="item",
                        value=cls.convert_pydantic_model(item),
                        type="object",
                    )
                    for item in model_items
                ]
            elif isinstance(field_value, dict):
                nested_dict_props: list[GenericProperty] = []
                dict_value = cast(dict[Any, Any], field_value)
                for key, val in dict_value.items():
                    if not isinstance(key, str) or not isinstance(val, str):
                        raise ValueError(
                            f"Erreur de type dans le champ '{field_name}'. "
                            f"La clé '{key}' a une valeur de type '{type(val).__name__}'. "
                            "Seuls les dictionnaires de type Dict[str, str] sont supportés."
                        )
                    nested_dict_props.append(
                        GenericProperty(name=key, value=val, type="string")
                    )
                final_value = nested_dict_props
                ui_type = "object"
            elif ui_type == "date" and isinstance(field_value, (date, datetime)):
                final_value = field_value.isoformat()
            elif isinstance(field_value, Decimal):
                final_value = float(field_value)

            properties.append(
                GenericProperty(
                    name=field_name, value=final_value, type=ui_type, anomaly=anomaly
                )
            )

        return properties

    @classmethod
    def _infer_ui_type(
        cls, annotation: Any, runtime_value: Any
    ) -> Literal["string", "number", "boolean", "object", "date", "list"]:
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if args:
                annotation = args[0]

        origin = get_origin(annotation)
        args = get_args(annotation)

        # Dict annotations are treated as objects; values are handled in the caller.
        if origin is dict or origin is Dict:
            return "object"

        # A. Optional types / Unions
        if origin is Union:
            target_args: list[Any] = [
                a
                for a in args
                if a is not type(None)
                and not (isinstance(a, type) and issubclass(a, InvalidProperty))
            ]
            if target_args:
                return cls._infer_ui_type(target_args[0], None)

        # B. Lists
        if origin is list or annotation is list:
            return "list"

        # C. Literals
        if origin is Literal:
            if args:
                first_arg = args[0]
                if isinstance(first_arg, str):
                    return "string"
                if isinstance(first_arg, (int, float)):
                    return "number"
                if isinstance(first_arg, bool):
                    return "boolean"
            return "string"

        # D. Primitives
        if annotation in (date, datetime):
            return "date"
        if annotation is str:
            return "string"
        if annotation in (int, float, Decimal):
            return "number"
        if annotation is bool:
            return "boolean"

        # E. Runtime fallback
        if runtime_value is not None:
            if isinstance(runtime_value, (date, datetime)):
                return "date"
            if isinstance(runtime_value, bool):
                return "boolean"
            if isinstance(runtime_value, (int, float, Decimal)):
                return "number"
            if isinstance(runtime_value, str):
                return "string"
            if isinstance(runtime_value, list):
                return "list"
            if isinstance(runtime_value, dict):
                return "object"

        return "object"
