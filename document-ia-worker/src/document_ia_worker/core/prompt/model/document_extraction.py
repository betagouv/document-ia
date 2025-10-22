from typing import TypeVar, Generic

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class DocumentExtraction(BaseModel, Generic[T]):
    title: str
    type: str
    properties: T
