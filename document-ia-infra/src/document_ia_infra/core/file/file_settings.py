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


file_settings = FileSettings()
