from pydantic import BaseModel, Field, SecretStr, field_serializer

from document_ia_infra.core.model.types.secret import SecretPayloadStr


class FileInfo(BaseModel):
    filename: str = Field(description="File name")
    s3_key: SecretPayloadStr = Field(description="S3 key to retrieve the file")
    size: int = Field(description="Size of the file in bytes")
    content_type: str = Field(description="Content type of the file")
    uploaded_at: str = Field(description="Date where the file was uploaded")
    presigned_url: SecretPayloadStr = Field(
        description="Presigned URL to access the file only available for 1h"
    )

    @field_serializer("s3_key", when_used="json")
    def dump_secret_s3(self, value: SecretStr) -> str:
        return value.get_secret_value()

    @field_serializer("presigned_url", when_used="json")
    def dump_secret_presigned_url(self, value: SecretStr) -> str:
        return value.get_secret_value()
