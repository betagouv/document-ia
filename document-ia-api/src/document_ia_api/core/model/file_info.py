from dataclasses import dataclass
from typing import Optional


@dataclass
class FileInfo:
    filename: str
    size: int
    extension: str
    content_type: Optional[str]
    max_size_allowed: int
    allowed_types: list[str]

    def to_dict(self):
        return {
            "filename": self.filename,
            "size": self.size,
            "extension": self.extension,
            "content_type": self.content_type,
            "max_size_allowed": self.max_size_allowed,
            "allowed_types": self.allowed_types,
        }
