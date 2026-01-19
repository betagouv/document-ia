from openai import BaseModel


class HttpOcrResult(BaseModel):
    success: bool
    content: str
