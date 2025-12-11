import importlib
import inspect
from enum import Enum
from typing import Any, Type, cast

from pydantic import BaseModel

from .base_document_type_schema import BaseDocumentTypeSchema
from .field_metrics import Metric


def _find_extract_schema_in_module(
        module: Any,
) -> Type[BaseDocumentTypeSchema[BaseModel]] | None:
    """Search the given module for a class that represents an extract schema.

    Behavior:
    - Iterate over all classes defined in `module`.
    - Filter only classes actually defined in that module (ignore imports).
    - Return the first class that is a subclass of `BaseDocumentTypeSchema`
      and whose name ends with "ExtractSchema".

    Returns:
        The matching schema class (not an instance) if found, otherwise None.
    """
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        try:
            if issubclass(obj, BaseDocumentTypeSchema) and obj.__name__.endswith(
                    "ExtractSchema"
            ):
                return cast(Type[BaseDocumentTypeSchema[BaseModel]], obj)
        except TypeError:
            continue
    return None


def resolve_extract_schema(name: str) -> BaseDocumentTypeSchema[BaseModel]:
    """Import the module for a document type and return its ExtractSchema instance.

    Convention (simple and robust):
    - Attempt to import the package/module `document_type.<name>`.
    - Search that module for an exported alias/class named `ExtractSchema` or
      for any class whose name ends with `ExtractSchema`.
    - If no such class is found, raise ImportError explaining the failure.

    Returns:
        An instance of the discovered ExtractSchema class.

    Raises:
        ImportError: if the module cannot be imported or no ExtractSchema class is found.
    """

    base_pkg = __name__
    module_name = f"{base_pkg}.{name}"
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ImportError(f"Cannot import module {module_name}") from exc

    schema_cls = _find_extract_schema_in_module(module)
    if schema_cls is None:
        raise ImportError(f"No ExtractSchema class found for {name}")
    return schema_cls()  # type: ignore[call-arg]


class SupportedDocumentType(str, Enum):
    CNI = "cni"
    PASSEPORT = "passeport"
    PERMIS_CONDUIRE = "permis_conduire"
    AVIS_IMPOSITION = "avis_imposition"
    ATTESTATION_AFFILIATION = "attestation_affiliation"
    BULLETIN_SALAIRE = "bulletin_salaire"
    QUITTANCE_LOYER = "quittance_loyer"
    FACTURE_ENERGIE = "facture_energie"
    ATTESTATION_CONTRAT_ENERGIE = "attestation_contrat_energie"

    @staticmethod
    def from_str(label: str) -> "SupportedDocumentType":
        label = label.lower()
        try:
            return SupportedDocumentType(label)
        except ValueError:
            raise ValueError(f"Unknown SupportedDocumentType: {label}")
__all__ = [
    "BaseDocumentTypeSchema",
    "SupportedDocumentType",
    "Metric",
    "resolve_extract_schema",
]
