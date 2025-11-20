"""Configuration utilities for the application."""

from pathlib import Path
from pydantic import Field
from pydantic_settings import SettingsConfigDict, BaseSettings


class Config(BaseSettings):
    """Application configuration using Pydantic BaseSettings."""
    
    @staticmethod
    def _find_env_file(filename: str = ".env") -> str | None:
        # Start from this file's directory and walk up to filesystem root looking for filename
        current = Path(__file__).resolve().parent
        root = current.anchor
        while True:
            candidate = current / filename
            if candidate.exists():
                return str(candidate)
            if str(current) == root:
                break
            current = current.parent
        return None

    _env_path = _find_env_file()
    # Extra env vars should be ignored so adding unrelated keys in the .env won't raise errors.
    model_config = SettingsConfigDict(
        env_file=_env_path or "", env_prefix="", extra="ignore"
    )
    
    # Project paths
    ROOT_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)
    
    @property
    def SRC_DIR(self) -> Path:
        return self.ROOT_DIR / "src"
    
    @property
    def DATA_DIR(self) -> Path:
        return self.ROOT_DIR / "data"
    
    # App settings
    APP_TITLE: str = Field(default="Streamlit App")
    PAGE_ICON: str = Field(default="📊")
    LAYOUT: str = Field(default="wide")

    # Configuration related to the Document IA API
    DOCUMENT_IA_BASE_URL: str = Field(default="https://api.staging.document-ia.beta.gouv.fr/")
    DOCUMENT_IA_API_KEY: str | None = Field(default=None)
    
    # S3 Configuration
    S3_ENDPOINT: str | None = Field(default=None)
    S3_ACCESS_KEY: str | None = Field(default=None)
    S3_SECRET_KEY: str | None = Field(default=None)
    S3_BUCKET_NAME: str | None = Field(default=None)
    S3_REGION: str | None = Field(default=None)
    
    # Label Studio Configuration
    LABEL_STUDIO_URL: str | None = Field(default=None)
    LABEL_STUDIO_API_KEY: str | None = Field(default=None)
    ML_BACKEND_URL: str | None = Field(default=None)
    ALLOW_INSECURE_REQUESTS: bool = Field(default=False)
    
    def ensure_directories(self):
        """Ensure necessary directories exist."""
        self.DATA_DIR.mkdir(exist_ok=True)


# Create singleton instance
config = Config()