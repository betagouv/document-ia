from typing import TypeVar, Optional, Callable

from sqlalchemy import inspect as _sa_inspect

from document_ia_infra.data.database import Base

R = TypeVar("R", bound=Base)
T = TypeVar("T")


def get_relationships_entities_if_loaded_list(
    entity: Base, field_name: str, mapper_function: Callable[[R], T]
) -> Optional[list[T]]:
    return_val: Optional[list[T]] = None
    try:
        state = _sa_inspect(entity)
        is_loaded = True
        # If sqlalchemy inspection is available, determine if attribute is unloaded
        if hasattr(state, "unloaded"):
            is_loaded = field_name not in state.unloaded
        if is_loaded:
            current = getattr(entity, field_name, None)
            if current:
                return_val = [mapper_function(item) for item in current]  # type: ignore
    except Exception:
        return_val = None

    return return_val


def get_relationship_entity_if_loaded(
    entity: Base, field_name: str, mapper_function: Callable[[R], T]
) -> Optional[T]:
    return_val: Optional[T] = None
    try:
        state = _sa_inspect(entity)
        is_loaded = True
        # If sqlalchemy inspection is available, determine if attribute is unloaded
        if hasattr(state, "unloaded"):
            is_loaded = field_name not in state.unloaded
        if is_loaded:
            current = getattr(entity, field_name, None)
            if current:
                return_val = mapper_function(current)
    except Exception:
        return_val = None

    return return_val
