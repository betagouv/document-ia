from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class MistralOcrSettings(BaseDocumentIaSettings):
    MISTRAL_OCR_API_KEY: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    MISTRAL_ORC_BASE_URL: str | None = Field(default=None, alias="OPENAI_BASE_URL")


mistral_ocr_settings = MistralOcrSettings()
