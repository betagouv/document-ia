from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class DeepseekOCRSettings(BaseDocumentIaSettings):
    DEEPSEEK_OCR_API_KEY: SecretStr | None = Field(default=None)
    DEEPSEEK_OCR_BASE_URL: str | None = Field(default=None)


deepseek_ocr_settings = DeepseekOCRSettings()
