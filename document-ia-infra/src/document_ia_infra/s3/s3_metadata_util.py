from __future__ import annotations

import re
import unicodedata
from typing import Optional, Dict


def _to_ascii(text: str) -> str:
    """Normalize unicode text to ASCII-safe representation.

    - Use NFKD to decompose accentuated letters (e.g., "é" -> "e" + accent)
    - Drop non-ASCII code points
    - Strip surrounding whitespace
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_bytes = normalized.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii").strip()


def _sanitize_key(key: str) -> str:
    """Sanitize metadata key for S3 user-defined metadata.

    Constraints (practical/safe subset):
    - ASCII only
    - Lowercase
    - Replace whitespace with '-'
    - Keep only [a-z0-9._-]
    - Collapse repeats of '-'
    """
    key_ascii = _to_ascii(key).lower()
    key_ascii = re.sub(r"\s+", "-", key_ascii)
    # Drop any char not safe
    key_ascii = re.sub(r"[^a-z0-9._-]", "", key_ascii)
    # Collapse consecutive '-'
    key_ascii = re.sub(r"-+", "-", key_ascii)
    # Avoid empty keys
    return key_ascii or "meta"


def _sanitize_value(value: str) -> str:
    """Sanitize metadata value for HTTP header safety (ASCII-only).

    - ASCII only (drop non-ASCII)
    - Replace CR/LF by space to avoid header injection issues
    - Trim surrounding whitespace
    """
    val_ascii = _to_ascii(value)
    # Replace CR/LF and tabs with a single space
    val_ascii = re.sub(r"[\r\n\t]+", " ", val_ascii)
    # Optionally, collapse multiple spaces
    val_ascii = re.sub(r"\s{2,}", " ", val_ascii)
    return val_ascii


def sanitize_metadata(metadata: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return a sanitized copy of user metadata for S3.

    S3 user metadata (x-amz-meta-*) must be HTTP-header friendly. Some SDKs
    and proxies reject non-ASCII. This function:
    - Converts keys/values to ASCII (NFKD -> ASCII, drop others)
    - Normalizes keys to a safe subset [a-z0-9._-] and lowercase
    - Replaces whitespace in keys with '-'
    - Removes CR/LF/TAB from values

    If ``metadata`` is None, returns an empty dict.

    Note: If two distinct input keys collapse to the same sanitized key,
    the last one wins.
    """
    if metadata is None:
        return {}

    sanitized: Dict[str, str] = {}

    for raw_key, raw_val in metadata.items():
        key = _sanitize_key(str(raw_key))
        val = _sanitize_value(str(raw_val))
        sanitized[key] = val

    return sanitized
