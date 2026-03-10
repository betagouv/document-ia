from typing import Annotated, Union

from pydantic import Field
from document_ia_api.api.contracts.execution.started import ExecutionStartedModel
from document_ia_api.api.contracts.execution.success import ExecutionSuccessModel
from document_ia_api.api.contracts.execution.failed import ExecutionFailedModel

# Discriminated union on "status"
ExecutionResponse = Annotated[
    Union[ExecutionStartedModel, ExecutionSuccessModel, ExecutionFailedModel],
    Field(discriminator="status"),
]
