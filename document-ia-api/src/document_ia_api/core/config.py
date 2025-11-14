from typing import Dict, List

from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class FileSettings(BaseDocumentIaSettings):
    # File upload configuration
    MAX_FILE_SIZE: int = Field(
        default=26214400, validation_alias="MAX_FILE_SIZE"
    )  # 25MB in bytes

    ALLOWED_MIME_TYPES: Dict[str, List[str]] = {
        "application/pdf": [".pdf"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
    }


class ApiKeySettings(BaseDocumentIaSettings):
    API_KEY_PEPPER_HASH: str = Field(
        default="default_pepper_hash_value", validation_alias="API_KEY_PEPPER_HASH"
    )

    API_KEY_PEPPER_CHK: str = Field(
        default="default_pepper_chk_value", validation_alias="API_KEY_PEPPER_CHK"
    )

    API_KEY_VERSION: int = Field(default=1, validation_alias="API_KEY_VERSION")

    APP_ENV: str = Field(default="prod", validation_alias="APP_ENV")

    DOCUMENT_IA_API_KEY: str = Field(default="", validation_alias="DOCUMENT_IA_API_KEY")


settings = FileSettings()
api_key_settings = ApiKeySettings()
