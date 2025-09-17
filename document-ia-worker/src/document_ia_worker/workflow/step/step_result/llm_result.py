from pydantic import BaseModel


class LLMResult(BaseModel):
    data: BaseModel
