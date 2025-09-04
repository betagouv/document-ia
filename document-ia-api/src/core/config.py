import os
from typing import Dict, List
from pydantic_settings import BaseSettings


class FileSettings(BaseSettings):
    # File upload configuration
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "26214400"))  # 25MB in bytes

    ALLOWED_MIME_TYPES: Dict[str, List[str]] = {
        "application/pdf": [".pdf"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
    }


settings = FileSettings()
