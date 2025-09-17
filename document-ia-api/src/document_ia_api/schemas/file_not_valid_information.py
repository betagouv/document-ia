from typing import Optional

from pydantic import BaseModel, Field


class FileNoteValidInformation(BaseModel):
    filename: str = Field(description="The name of the file")
    size: int = Field(description="The current size of the file sent to API")
    extension: str = Field(description="The current file extension")
    content_type: Optional[str] = Field(
        description="The detected content type of the file"
    )
    max_size_allowed: int = Field(description="Max file size allowed by API")
    allowed_types: list[str] = Field(description="Mime types allowed by API")
