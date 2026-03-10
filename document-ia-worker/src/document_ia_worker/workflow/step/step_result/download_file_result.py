from pydantic import BaseModel


class DownloadFileResult(BaseModel):
    file_path: str
    content_type: str
