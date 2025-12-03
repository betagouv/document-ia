from itertools import chain
from pathlib import Path
from typing import Optional

from document_ia_infra.core.file.file_settings import file_settings


def get_file_extension(file_name: str) -> str:
    """Return normalized extension (with dot), lowercased, or '' if none."""
    return Path(file_name).suffix.lower()


def validate_file_extension(file_name: Optional[str]) -> bool:
    """Validate if the file extension is allowed based on settings."""
    if file_name is None:
        return False

    extensions_to_mime = set(
        chain.from_iterable(file_settings.ALLOWED_MIME_TYPES.values())
    )
    extension = get_file_extension(file_name)

    return extension in extensions_to_mime
