from pydantic import SecretStr, Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class NanonetsSettings(BaseDocumentIaSettings):
    NANONETS_API_KEY: SecretStr | None = Field(default=None)
    NANONETS_BASE_URL: str | None = Field(default=None)


nanonets_settings = NanonetsSettings()