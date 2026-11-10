import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from fastapi import UploadFile
from pydantic import BaseModel


def _canonicalize_value(val: Any) -> Any:
    """Recursively order mapping keys, leaving every value and its type untouched.

    Only key ordering is normalized: two payloads share a fingerprint when they
    are the same JSON document, never because a value was dropped or converted.
    A nested `null`, and a string that happens to contain JSON, must survive as
    they are — `{"source": "{}"}` and `{"source": {}}` are different requests
    even though they serialize alike once parsed loosely.
    """
    if isinstance(val, BaseModel):
        return _canonicalize_value(val.model_dump(mode="json"))
    if isinstance(val, Mapping):
        mapping = cast(Mapping[object, object], val)
        sorted_pairs = sorted(mapping.items(), key=lambda pair: str(pair[0]))
        return {str(k): _canonicalize_value(v) for k, v in sorted_pairs}
    if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
        seq = cast(Sequence[object], val)
        return [_canonicalize_value(item) for item in seq]
    return val


def _parse_form_json_field(raw: Any) -> Any:
    """Parse a multipart form field that carries a JSON document.

    Form values arrive as text. Parsing happens once, at the field boundary, so
    that key ordering rather than textual formatting decides the fingerprint and
    nested values keep their JSON types. A field that is not valid JSON is kept
    verbatim: request validation rejects it later, and the fingerprint must still
    be deterministic.
    """
    if not isinstance(raw, str):
        return raw

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _canonicalize_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Canonicalize the multipart form parameters of an execution request.

    Only the outer form fields are normalized: an absent field arrives as `None`
    and is dropped, because FastAPI reports an omitted field and an empty one
    identically. Every value is then parsed once from its JSON text and only
    key-sorted, so distinct payloads keep distinct types.
    """
    if not params:
        return {}

    canonical: dict[str, Any] = {}
    for key in sorted(params, key=str):
        raw = params[key]
        if raw is None:
            continue
        canonical[str(key)] = _canonicalize_value(_parse_form_json_field(raw))
    return canonical


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
    normalized_params = _canonicalize_params(params)
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
