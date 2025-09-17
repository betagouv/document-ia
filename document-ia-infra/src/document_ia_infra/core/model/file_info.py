from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    filename: str = Field(description="File name")
    s3_key: str = Field(description="S3 key to retrieve the file")
    size: int = Field(description="Size of the file in bytes")
    content_type: str = Field(description="Content type of the file")
    uploaded_at: str = Field(description="Date where the file was uploaded")
    presigned_url: str = Field(
        description="Presigned URL to access the file only available for 1h"
    )
