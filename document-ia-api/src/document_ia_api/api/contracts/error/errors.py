from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    type: str = Field(default="about:blank", description="RFC7807 type URI")
    title: str
    status: int
    detail: Optional[str] = None
    instance: Optional[str] = None
    code: Optional[str] = Field(default=None, description="Stable app-level error code")
    trace_id: Optional[str] = None
    errors: Optional[Dict[str, Any]] = None  # field -> messages


class AppError(Exception):
    def __init__(
        self,
        *,
        status: int,
        title: str,
        detail: Optional[str] = None,
        code: Optional[str] = None,
        type_: str = "about:blank",
        errors: Optional[Dict[str, Any]] = None,
    ):
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code
        self.type_ = type_
        self.errors = errors
