from typing import Generic, TypeVar, Any, cast

from document_ia_schemas import SupportedDocumentType, resolve_extract_schema
from pydantic import BaseModel, Field, model_validator, field_serializer

T = TypeVar("T", bound=BaseModel)


class DocumentExtraction(BaseModel, Generic[T]):
    title: str
    type: SupportedDocumentType
    properties: T = Field(description="Document properties")

    ## This will allow to deserialize `properties` into the correct Pydantic model based on `type`
    @model_validator(mode="before")
    @classmethod
    def _coerce_properties_from_type(cls, data: Any) -> Any:
        """If properties is a dict, use `type` to instantiate the proper Pydantic model.

        This preserves the generic usage while ensuring round-trip (de)serialization.
        """
        try:
            if isinstance(data, dict):
                dict_data = cast(dict[str, Any], data)
                props_raw = dict_data.get("properties")
                doc_type_raw = dict_data.get("type")
                if isinstance(props_raw, dict) and isinstance(
                    doc_type_raw, (str, SupportedDocumentType)
                ):
                    props = cast(dict[str, Any], props_raw)
                    # normalize doc_type to string
                    doc_type_str: str = (
                        doc_type_raw.value
                        if isinstance(doc_type_raw, SupportedDocumentType)
                        else doc_type_raw
                    )
                    schema_cls = resolve_extract_schema(doc_type_str)
                    model_cls = getattr(schema_cls, "document_model", None)
                    if model_cls is not None:
                        # Replace raw dict with a concrete BaseModel instance
                        return cast(
                            Any, {**dict_data, "properties": model_cls(**props)}
                        )
        except Exception:
            # Fail-soft: keep original data if anything goes wrong
            return cast(Any, data)
        return cast(Any, data)

    ## This will allow to serialize `properties` back to dict
    @field_serializer("properties")
    def _serialize_properties(self, value: BaseModel) -> Any:
        # Render nested Pydantic model as dict (keep aliases, drop None)
        return value.model_dump(by_alias=True, exclude_none=True)
