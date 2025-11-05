from __future__ import annotations

from typing import Annotated, Optional, Union, Any

from pydantic import BaseModel, Field

from document_ia_api.api.middleware.aggregator_middleware import (
    _unwrap_is_secret_type,
    _unwrap_model_type,
    _build_mask_map,
    _apply_mask,
)
from document_ia_api.api.contracts.execution.result import (
    ExtractionResult,
)
from document_ia_infra.core.model.types.secret import (
    SecretPayloadStr,
    SecretPayloadBytes,
)


class _ForwardWrapper(BaseModel):
    # forward ref by string
    inner: "ExtractionResult"


def test_unwrap_is_secret_type_variants():
    assert _unwrap_is_secret_type(SecretPayloadStr)
    assert _unwrap_is_secret_type(Optional[SecretPayloadStr])
    assert _unwrap_is_secret_type(Annotated[SecretPayloadStr, Field(description="x")])
    assert _unwrap_is_secret_type(SecretPayloadBytes)

    class NotSecret(BaseModel):
        x: int

    assert _unwrap_is_secret_type(NotSecret) is False


def test_unwrap_model_type_handles_collections_and_unions():
    # Direct
    assert _unwrap_model_type(ExtractionResult, ExtractionResult) is ExtractionResult
    # Optional
    assert _unwrap_model_type(Optional[ExtractionResult], ExtractionResult) is ExtractionResult
    # Union with None
    assert _unwrap_model_type(Union[ExtractionResult, None], ExtractionResult) is ExtractionResult
    # List
    assert _unwrap_model_type(list[ExtractionResult], ExtractionResult) is ExtractionResult
    # Annotated
    AnnotatedType = Annotated[ExtractionResult, Field(description="wrapped")]
    assert _unwrap_model_type(AnnotatedType, ExtractionResult) is ExtractionResult


def test_build_mask_map_for_extraction_models():
    # Expect mask on properties.value (nested list of model)
    mask_map = _build_mask_map(ExtractionResult)
    assert "properties" in mask_map
    assert isinstance(mask_map["properties"], dict)
    assert mask_map["properties"].get("value") is True


def test_apply_mask_on_payload_with_none_and_values():
    payload: dict[str, Any] = {
        "type": "CNI",
        "properties": [
            {"name": "firstname", "value": "Alice", "type": "str"},
            {"name": "age", "value": None, "type": "int"},
        ],
    }
    mask_map = {"properties": {"value": True}}

    masked = _apply_mask(payload, mask_map)

    assert masked["properties"][0]["value"] == "***"
    assert masked["properties"][1]["value"] is None
    # Unaffected keys remain unchanged
    assert masked["properties"][0]["name"] == "firstname"


def test_build_mask_map_with_forward_ref_wrapper():
    # Validate that a forward-ref field still yields the nested mask
    class Wrapper(BaseModel):
        result: "ExtractionResult"

    # Pydantic may need rebuild to resolve forward refs
    try:
        Wrapper.model_rebuild()
    except Exception:
        pass

    mask_map = _build_mask_map(Wrapper)
    assert "result" in mask_map
    assert isinstance(mask_map["result"], dict)
    assert mask_map["result"].get("properties", {}).get("value") is True
