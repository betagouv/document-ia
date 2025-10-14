from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_infra.core.model.types.secret import SecretPayloadStr


class ExecutionStartedData(BaseModel):
    created_at: datetime
    file_name: str
    content_type: str
    presigned_url: SecretPayloadStr


class ExecutionStartedModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.STARTED]
    data: ExecutionStartedData
