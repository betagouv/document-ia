import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from fastapi import UploadFile
from pydantic import BaseModel


def _canonicalize_value(val: Any) -> Any:
    """Recursively canonicalize arbitrary values for deterministic serialization."""
    if val is None:
        return None
    if isinstance(val, str):
        trimmed = val.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (
            trimmed.startswith("[") and trimmed.endswith("]")
        ):
            try:
                parsed: Any = json.loads(trimmed)
                return _canonicalize_value(parsed)
            except Exception:
                return trimmed
        return trimmed
    if isinstance(val, BaseModel):
        return _canonicalize_value(val.model_dump(mode="json", exclude_none=True))
    if isinstance(val, Mapping):
        mapping = cast(Mapping[object, object], val)
        sorted_pairs = sorted(mapping.items(), key=lambda pair: str(pair[0]))
        return {
            str(k): _canonicalize_value(v) for k, v in sorted_pairs if v is not None
        }
    if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
        seq = cast(Sequence[object], val)
        return [_canonicalize_value(item) for item in seq]
    return val


async def compute_request_fingerprint(
    *,
    method: str,
    path: str,
    file: UploadFile | None = None,
    file_url: str | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic SHA-256 fingerprint for an execution request.

    Combines:
    - HTTP method (e.g. POST)
    - Canonical path (e.g. /api/v2/workflows/{id}/execute)
    - Canonicalized JSON parameters (metadata, overrides, etc.)
    - Document content:
      - UploadFile: streamed in 64KB chunks, strictly followed by `await file.seek(0)`.
      - file_url: normalized URL string.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).
    """
    hasher = hashlib.sha256()

    # Method & path
    hasher.update(method.upper().strip().encode("utf-8"))
    hasher.update(b"\n")
    hasher.update(path.strip().encode("utf-8"))
    hasher.update(b"\n")

    # Canonical params
    normalized_params = _canonicalize_value(params or {})
    params_bytes = json.dumps(
        normalized_params, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    hasher.update(params_bytes)
    hasher.update(b"\n")

    # Document
    if file is not None:
        hasher.update(b"file:")
        if file.filename:
            hasher.update(file.filename.encode("utf-8"))
        hasher.update(b"\n")

        file_hasher = hashlib.sha256()
        chunk_size = 64 * 1024
        await file.seek(0)
        try:
            while chunk := await file.read(chunk_size):
                file_hasher.update(chunk)
        finally:
            await file.seek(0)

        hasher.update(file_hasher.digest())
    elif file_url is not None:
        hasher.update(b"file_url:")
        hasher.update(file_url.strip().encode("utf-8"))

    return hasher.hexdigest()
