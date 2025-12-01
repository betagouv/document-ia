from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional, Union, get_args, get_origin, Dict, cast

from pydantic import BaseModel, Field


class GenericProperty(BaseModel):
    name: str
    value: Union[str, int, float, bool, list["GenericProperty"], None] = Field(
        json_schema_extra={"x-mask": True},
    )
    type: Literal["string", "number", "boolean", "object", "date"]

    @classmethod
    def convert_pydantic_model(
        cls, model: Optional[BaseModel]
    ) -> list["GenericProperty"]:
        properties: list["GenericProperty"] = []
        if model is None:
            return properties

        model_fields = getattr(type(model), "model_fields", {})

        for field_name, field_value in model:
            # 1. Gestion des Nested Models (Pydantic) -> recursion
            if isinstance(field_value, BaseModel):
                nested_props = cls.convert_pydantic_model(field_value)
                properties.append(
                    GenericProperty(
                        name=field_name,
                        value=nested_props,
                        type="object",
                    )
                )
                continue

            # 2. Gestion stricte des Dict[str, str]
            if isinstance(field_value, dict):
                nested_dict_props: list[GenericProperty] = []

                for key, val in field_value.items():  # pyright: ignore [reportUnknownVariableType]
                    safe_key: str = cast(str, key)
                    safe_val: Any = cast(Any, val)
                    # Validation stricte : on refuse tout ce qui n'est pas str
                    if not isinstance(val, str):
                        raise ValueError(
                            f"Erreur de type dans le champ '{field_name}'. "
                            f"La clé '{safe_key}' a une valeur de type '{type(safe_val).__name__}'. "
                            "Seuls les dictionnaires de type Dict[str, str] sont supportés."
                        )

                    nested_dict_props.append(
                        GenericProperty(name=safe_key, value=val, type="string")
                    )

                properties.append(
                    GenericProperty(
                        name=field_name,
                        value=nested_dict_props,
                        type="object",
                    )
                )
                continue

            # 3. Récupération de l'annotation classique
            field_info = model_fields.get(field_name)
            annotation: Any = (  # pyright: ignore [reportUnknownVariableType]
                field_info.annotation
                if field_info and field_info.annotation is not None
                else type(field_value)
            )

            # 4. Déduction du type UI
            ui_type = cls._infer_ui_type(annotation, field_value)

            # 5. Formatage spécifique
            final_value = field_value

            if ui_type == "date" and isinstance(field_value, (date, datetime)):
                final_value = field_value.isoformat()
            elif isinstance(field_value, Decimal):
                final_value = float(field_value)

            properties.append(
                GenericProperty(
                    name=field_name,
                    value=final_value,
                    type=ui_type,
                )
            )

        return properties

    @classmethod
    def _infer_ui_type(
        cls, annotation: Any, runtime_value: Any
    ) -> Literal["string", "number", "boolean", "object", "date"]:
        origin = get_origin(annotation)
        args = get_args(annotation)

        # Si l'annotation dit Dict, on retourne object (le contenu sera traité par la boucle principale)
        if origin is dict or origin is Dict:
            return "object"

        # A. Gestion des Optionnels
        if origin is Union and type(None) in args:
            non_none_args = [a for a in args if a is not type(None)]
            if non_none_args:
                return cls._infer_ui_type(non_none_args[0], None)

        # B. Gestion des Listes
        if origin is list or annotation is list:
            return "object"

        # C. Gestion des Literals
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

        # D. Primitifs
        if annotation in (date, datetime):
            return "date"
        if annotation is str:
            return "string"
        if annotation in (int, float, Decimal):
            return "number"
        if annotation is bool:
            return "boolean"

        # E. Fallback Runtime
        if runtime_value is not None:
            if isinstance(runtime_value, (date, datetime)):
                return "date"
            if isinstance(runtime_value, bool):
                return "boolean"
            if isinstance(runtime_value, (int, float, Decimal)):
                return "number"
            if isinstance(runtime_value, str):
                return "string"
            if isinstance(runtime_value, dict):
                return "object"

        return "object"
