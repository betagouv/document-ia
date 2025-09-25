import os

from dotenv import load_dotenv

load_dotenv()


class OpenAISettings:
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL")
    OPENAI_ENCODING_MODEL: str = os.getenv("OPENAI_ENCODING_MODEL", "gpt-4")


openai_settings = OpenAISettings()
