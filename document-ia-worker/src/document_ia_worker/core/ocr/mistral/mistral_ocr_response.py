from pydantic import BaseModel, Field


class MistralOcrReponsePage(BaseModel):
    index: int
    markdown: str


class MistralOcrResponse(BaseModel):
    id: str
    model: str
    pages: list[MistralOcrReponsePage] = Field(default=[])
