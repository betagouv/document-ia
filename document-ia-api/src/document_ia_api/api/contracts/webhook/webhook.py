from uuid import UUID

from pydantic import BaseModel, Field


class CreateWebHookRequest(BaseModel):
    url: str = Field(
        description="Url of the webhook", examples=["https://example.com/webhook"]
    )
    headers: dict[str, str] = Field(
        default={}, description="Headers to include in the webhook requests"
    )


class WebHookResult(BaseModel):
    id: str = Field(description="Webhook ID")
    organization_id: UUID = Field(description="Organization ID owning the webhook")
    url: str = Field(description="URL of the webhook")
    headers: dict[str, str] = Field(description="Webhook headers")
    created_at: str = Field(description="Webhook creation time (ISO8601)")
    updated_at: str = Field(description="Webhook update time (ISO8601)")
