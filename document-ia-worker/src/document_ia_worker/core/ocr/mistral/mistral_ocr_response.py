from pydantic import BaseModel, Field
from typing import Optional


class MistralOcrReponsePage(BaseModel):
    index: int
    markdown: str


class MistralOcrResponse(BaseModel):
    id: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    pages: list[MistralOcrReponsePage] = Field(default=[])
