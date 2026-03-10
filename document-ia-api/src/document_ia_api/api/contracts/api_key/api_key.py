from pydantic import BaseModel, Field

from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus


class APIKeyResult(BaseModel):
    id: str = Field(description="API key ID")
    prefix: str = Field(description="API key prefix (public part)")
    status: ApiKeyStatus = Field(description="API key status")
    created_at: str = Field(description="API key creation time (ISO8601)")
    updated_at: str = Field(description="API key update time (ISO8601)")


class APIKeyCreatedResult(APIKeyResult):
    key: str = Field(description="Full API key (private part)")


class UpdateAPIKeyStatusRequest(BaseModel):
    status: ApiKeyStatus = Field(description="New status for the API key")
