import re
from typing import Annotated, Any, Optional

from pydantic import BeforeValidator

TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:(?:m(?:onsieur)?|mme|madame|mlle|docteur|dr|prof(?:esseur)?|pr)\.?\s+)+",
    flags=re.IGNORECASE,
)


def normalize_identity(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value

    normalized_value = value.replace(",", " ").strip()
    normalized_value = TITLE_PREFIX_PATTERN.sub("", normalized_value)
    normalized_value = re.sub(r"\s+", " ", normalized_value).strip()
    return normalized_value or None


Identity = Annotated[Optional[str], BeforeValidator(normalize_identity)]
