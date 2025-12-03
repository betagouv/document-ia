from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.types.secret import SecretPayloadStr


class S3FileInfo(BaseModel):
    file_name: str
    content_type: str
    presigned_url: SecretPayloadStr


class ExecutionStartedData(BaseModel):
    created_at: datetime
    s3_file_info: Optional[S3FileInfo]
    file_url: Optional[str]


class ExecutionStartedModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.STARTED]
    data: ExecutionStartedData
