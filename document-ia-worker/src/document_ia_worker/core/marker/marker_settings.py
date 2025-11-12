from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class MarkerSettings(BaseDocumentIaSettings):
    MARKER_API_KEY: SecretStr | None = Field(default=None)
    MARKER_BASE_URL: str | None = Field(default=None)


marker_settings = MarkerSettings()
