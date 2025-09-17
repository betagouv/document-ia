import os

from dotenv import load_dotenv

load_dotenv()


class OpenAISettings:
    ALBERT_API_KEY: str | None = os.getenv("ALBERT_API_KEY")
    ALBERT_BASE_URL: str | None = os.getenv("ALBERT_BASE_URL")
    ENCODING_MODEL: str = os.getenv("ENCORING_MODEL", "gpt-4")
    ALBERT_SMALL_MODEL = "albert-small"
    ALBERT_LARGE_MODEL = "albert-large"


openai_settings = OpenAISettings()
