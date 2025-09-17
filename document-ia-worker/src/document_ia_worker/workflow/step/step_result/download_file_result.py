from dataclasses import dataclass


@dataclass
class DownloadFileResult:
    file_path: str
    content_type: str
