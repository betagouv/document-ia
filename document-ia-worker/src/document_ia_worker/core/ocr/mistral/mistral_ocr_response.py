from pydantic import BaseModel, Field
from typing import Optional


class MistralOcrTable(BaseModel):
    id: str
    content: str
    format_: Optional[str] = Field(default=None)


class MistralOcrReponsePage(BaseModel):
    index: int
    markdown: str
    tables: list[MistralOcrTable] = Field(default=[])


class MistralOcrResponse(BaseModel):
    id: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    pages: list[MistralOcrReponsePage] = Field(default=[])
