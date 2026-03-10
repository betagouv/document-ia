from __future__ import annotations

from typing import Any, Dict, get_args, get_origin, Type, Union

from pydantic import BaseModel, Field, create_model


def _is_basemodel_subclass(tp: Any) -> bool:
    try:
        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except Exception:
        return False


def _normalize_annotation(
    tp: Any, cache: Dict[type[BaseModel], type[BaseModel]]
) -> Any:
    """Return an annotation where BaseModel types are replaced by their normalized wrappers.

    Handles common containers: Optional[T], list[T], dict[str, T], Union[T1, T2].
    """
    origin = get_origin(tp)
    if origin is None:
        if _is_basemodel_subclass(tp):
            return get_response_format(tp, _cache=cache)
        return tp

    args = list(get_args(tp))

    if origin in (list, tuple, set, frozenset):
        return origin[tuple(_normalize_annotation(a, cache) for a in args)]  # type: ignore[index]
    if origin in (dict,):
        # Only normalize value type
        if len(args) == 2:
            return dict[
                _normalize_annotation(args[0], cache),
                _normalize_annotation(args[1], cache),
            ]  # type: ignore[index]
        return tp
    if origin is Union:
        return Union[tuple(_normalize_annotation(a, cache) for a in args)]  # type: ignore[index]

    # Fallback: leave as-is
    return tp


def get_response_format(
    model_cls: Type[BaseModel],
    _cache: Dict[type[BaseModel], type[BaseModel]] | None = None,
) -> Type[BaseModel]:
    """Build a dynamic Pydantic model that mirrors `model_cls` but strips alias and json_schema_extra.

    - Field names and types are preserved (types of nested BaseModel are normalized recursively).
    - Field-level alias/serialization_alias/validation_alias are removed.
    - json_schema_extra is not propagated.
    - Validators/serializers from the original model are NOT inherited; we build a fresh BaseModel.

    This wrapper is intended for use with the OpenAI client's structured parsing where
    we want names-only JSON (no aliases), while keeping the original model unchanged
    for prompt generation/documentation.
    """
    cache: Dict[type[BaseModel], type[BaseModel]] = _cache or {}
    if model_cls in cache:
        return cache[model_cls]

    fields: dict[str, tuple[Any, Any]] = {}

    for name, f in model_cls.model_fields.items():
        ann = f.annotation
        norm_ann = _normalize_annotation(ann, cache)

        # Preserve default if present; else mark as required
        if f.is_required():
            default = Field(description=f.description, examples=f.examples)
        else:
            default_val = f.default
            default = Field(
                default=default_val, description=f.description, examples=f.examples
            )

        fields[name] = (norm_ann, default)

    # Build a new model on top of BaseModel (clean, without aliases/extras)
    NewModel: Type[BaseModel] = create_model(
        f"{model_cls.__name__}OpenAI",
        __base__=BaseModel,
        **fields,  # type: ignore[arg-type]
    )

    cache[model_cls] = NewModel
    return NewModel
