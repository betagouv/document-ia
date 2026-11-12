from typing import Literal, Optional

from pydantic import BaseModel, Field, NonNegativeInt

from document_ia_api.api.contracts.execution.types import ExecutionStatus


class ExecutionFailedData(BaseModel):
    error_type: str
    failed_step: Optional[str]
    retry_count: NonNegativeInt
    workflow_id: str
    error_message: str


class ExecutionFailedModel(BaseModel):
    id: str
    status: Literal[ExecutionStatus.FAILED]
    data: ExecutionFailedData
    purged: bool = Field(
        default=False,
        description="Whether sensitive event data has been purged",
    )
