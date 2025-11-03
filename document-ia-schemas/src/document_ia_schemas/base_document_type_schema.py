from abc import ABC
from typing import TypeVar, Generic, Type, Any

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound=BaseModel)


class BaseDocumentTypeSchema(BaseModel, Generic[T], ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str = ""
    name: str = ""
    description: list[str] = []
    document_model: Type[T]

    # Clés à exclure du JSON Schema (issues de json_schema_extra sur les champs)
    # Ajustable par sous-classe si besoin (ex: {"metrics", "x-internal"})
    schema_extra_keys_excluded: set[str] = {"metrics"}

    def get_document_description_dict(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "description": self.description}

    def _strip_keys_recursive(self, obj: Any, keys_to_strip: set[str]) -> Any:
        """Supprime récursivement les clés spécifiées dans n'importe quel dict du schéma.

        - Parcourt dicts et lists
        - Retire les clés présentes dans keys_to_strip
        - Retourne l'objet (muté) pour chaînage
        """
        if isinstance(obj, dict):
            for k in list(obj.keys()):  # pyright: ignore [reportUnknownArgumentType, reportUnknownVariableType]
                if k in keys_to_strip:
                    obj.pop(k, None)  # pyright: ignore [reportUnknownMemberType, reportUnknownArgumentType]
                else:
                    obj[k] = self._strip_keys_recursive(obj[k], keys_to_strip)
        elif isinstance(obj, list):
            for i in range(len(obj)):  # pyright: ignore [reportUnknownArgumentType]
                obj[i] = self._strip_keys_recursive(obj[i], keys_to_strip)
        return obj  # pyright: ignore [reportUnknownVariableType]

    def get_json_schema_dict(self) -> dict[str, Any]:
        schema = self.document_model.model_json_schema(by_alias=False)
        # Nettoie les clés supplémentaires (json_schema_extra) si configurées
        if self.schema_extra_keys_excluded:
            schema = self._strip_keys_recursive(schema, self.schema_extra_keys_excluded)
        return schema
