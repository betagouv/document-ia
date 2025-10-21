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

    def get_document_description_dict(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "description": self.description}

    def get_json_schema_dict(self) -> dict[str, Any]:
        return self.document_model.model_json_schema(by_alias=False)
