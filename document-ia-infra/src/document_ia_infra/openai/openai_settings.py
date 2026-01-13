from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class OpenAISettings(BaseDocumentIaSettings):
    OPENAI_API_KEY: SecretStr | None = Field(default=None)
    OPENAI_BASE_URL: str | None = Field(default=None)
    OPENAI_ENCODING_MODEL: str = Field(
        default="gpt-4",
        description="Model used for token encoding to calculate request /response size",
    )
    OPENAI_TIMEOUT: int = Field(
        default=30, description="Timeout for OpenAI API requests in seconds"
    )
    OPENAI_MAX_RETRIES: int = Field(
        default=1, description="Maximum number of retries for OpenAI API requests"
    )


openai_settings = OpenAISettings()
