from pathlib import Path
from pydantic_settings import SettingsConfigDict, BaseSettings


class BaseDocumentIaSettings(BaseSettings):
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
