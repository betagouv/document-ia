from typing import TypeVar, Generic

from pydantic import BaseModel
from pydantic.generics import GenericModel

T = TypeVar("T", bound=BaseModel)


class DocumentExtraction(GenericModel, Generic[T]):
    title: str
    type: str
    properties: T
