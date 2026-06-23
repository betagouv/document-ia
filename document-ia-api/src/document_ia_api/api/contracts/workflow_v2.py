from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel

from document_ia_api.schemas.workflow import WorkflowExecutionDataV2


ParameterDefaultValue = str | int | float | bool | list[str]


class WorkflowV2ParameterItems(BaseModel):
    """Schema for array items in a parameter rule."""

    type: Optional[str] = Field(default=None, description="Type of each array item.")
    enum: Optional[list[str]] = Field(
        default=None, description="Allowed values for each array item."
    )


class WorkflowV2ParameterVariant(BaseModel):
    """One variant of a composite (oneOf) parameter rule."""

    type: Optional[str] = Field(default=None, description="Variant type.")
    enum: Optional[list[str]] = Field(
        default=None, description="Allowed values for this variant."
    )
    items: Optional[WorkflowV2ParameterItems] = Field(
        default=None,
        description="Array items schema when variant type is array.",
    )


class WorkflowV2StepParameterRuleRaw(BaseModel):
    """Parameter rule as loaded from workflow YAML."""

    model_config = ConfigDict(populate_by_name=True)

    type: Optional[str] = Field(
        default=None, description="Parameter type in JSON schema style."
    )
    description: Optional[str] = Field(
        default=None, description="Human-readable description of the parameter."
    )
    default: Optional[ParameterDefaultValue] = Field(
        default=None,
        description="Default value used when no override is provided.",
    )
    enum: Optional[list[str]] = Field(
        default=None, description="Allowed values when the parameter is enumerated."
    )
    one_of: Optional[list[WorkflowV2ParameterVariant]] = Field(
        default=None,
        alias="oneOf",
        description="Alternative schemas allowed for the parameter.",
    )


class WorkflowV2StepRaw(BaseModel):
    """Workflow step as loaded from workflow YAML."""

    action: str = Field(
        description="Step action identifier executed by the workflow engine."
    )
    params: Optional[dict[str, WorkflowV2StepParameterRuleRaw]] = Field(
        default=None,
        description="Step parameters and their validation/configuration rules.",
    )


class WorkflowV2RawItem(BaseModel):
    """Workflow definition as loaded from workflow YAML."""

    id: str = Field(description="Unique workflow identifier.")
    name: str = Field(description="Display name of the workflow.")
    description: str = Field(description="Functional description of the workflow.")
    version: str = Field(description="Workflow version.")
    enabled: bool = Field(description="Whether this workflow is currently enabled.")
    supported_file_types: list[str] = Field(
        description="MIME types accepted by this workflow."
    )
    max_file_size_mb: int = Field(description="Maximum accepted file size in MB.")
    processing_timeout_minutes: int = Field(
        description="Maximum execution timeout in minutes."
    )
    steps: list[WorkflowV2StepRaw] = Field(
        description="Ordered steps composing the workflow."
    )


class WorkflowV2StepParameterRuleResponse(BaseModel):
    """Validation/display rule returned by the v2 API."""

    model_config = ConfigDict(populate_by_name=True)

    type: Optional[str] = Field(
        default=None, description="Parameter type in JSON schema style."
    )
    description: Optional[str] = Field(
        default=None, description="Human-readable description of the parameter."
    )
    default: Optional[ParameterDefaultValue] = Field(
        default=None,
        description="Default value used when no override is provided.",
    )
    enum: Optional[list[str]] = Field(
        default=None, description="Allowed values when the parameter is enumerated."
    )
    one_of: Optional[list[WorkflowV2ParameterVariant]] = Field(
        default=None,
        alias="oneOf",
        description="Alternative schemas allowed for the parameter.",
    )


class WorkflowV2StepResponse(BaseModel):
    """One step of a workflow definition returned by API."""

    action: str = Field(
        description="Step action identifier executed by the workflow engine."
    )
    params: Optional[dict[str, WorkflowV2StepParameterRuleResponse]] = Field(
        default=None,
        description="Step parameters and their validation/configuration rules.",
    )


class WorkflowV2ResponseItem(BaseModel):
    """Workflow definition returned by the v2 API."""

    id: str = Field(description="Unique workflow identifier.")
    name: str = Field(description="Display name of the workflow.")
    description: str = Field(description="Functional description of the workflow.")
    version: str = Field(description="Workflow version.")
    enabled: bool = Field(description="Whether this workflow is currently enabled.")
    supported_file_types: list[str] = Field(
        description="MIME types accepted by this workflow."
    )
    max_file_size_mb: int = Field(description="Maximum accepted file size in MB.")
    processing_timeout_minutes: int = Field(
        description="Maximum execution timeout in minutes."
    )
    steps: list[WorkflowV2StepResponse] = Field(
        description="Ordered steps composing the workflow."
    )


class WorkflowV2ListResponse(BaseModel):
    """Envelope returned by GET /api/v2/workflows/."""

    status: str = Field(description="Response status.", examples=["success"])
    data: list[WorkflowV2ResponseItem] = Field(
        description="List of workflows available on the API."
    )
    message: str = Field(
        description="Human-readable response message.",
        examples=["Available workflows retrieved successfully"],
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Response timestamp in ISO format.",
    )


class WorkflowV2StepParamOverride(BaseModel):
    """One parameter override for a specific workflow step."""

    param: str = Field(
        description="Parameter name to override in the target step.",
        examples=["document_type"],
    )
    value: Any = Field(
        description="Override value for the parameter.",
        examples=["passeport"],
    )


class WorkflowV2OverridePayload(
    RootModel[dict[str, list[WorkflowV2StepParamOverride]]]
):
    """Override payload from multipart field `override`.

    Keys are workflow step action names and values are lists of parameter overrides.
    """


class WorkflowV2ExecuteResponse(BaseModel):
    """Validation-only response for v2 execute endpoint (phase 1)."""

    status: str = Field(description="Response status.", examples=["success"])
    data: WorkflowExecutionDataV2 = Field(description="Execution payload.")
    message: str = Field(
        description="Human-readable response message.",
        examples=["Workflow override is valid"],
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Response timestamp in ISO format.",
    )
