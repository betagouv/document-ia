import io
import time
import json
import pydantic
import datetime
from enum import StrEnum
from typing import Any
import requests

from document_ia_evals.utils.config import config
from urllib.parse import urljoin


# TODO: import from `document-ia-api` package instead
class WorkflowExecuteResponse(pydantic.BaseModel):
    """Schema for workflow execution response."""

    status: str
    data: Any
    message: str
    timestamp: datetime.datetime

class ExecutionStatus(StrEnum):
    # TODO: retrieve possible values from `document-ia-api` package
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class ExecutionModel(pydantic.BaseModel):
    id: str
    status: str
    data: Any

def execute_workflow(
    workflow_name: str,
    file: io.BytesIO,
    api_token: str,
    metadata: dict[str, Any] | None = None,
    extraction_parameters: dict[str, Any] | None = None,
    classification_parameters: dict[str, Any] | None = None
) -> WorkflowExecuteResponse:
    """"Execute a workflow on the Document IA API.

    Args:
        workflow_name (str): The name of the workflow to execute.
        file: The file-like object to process.
        api_token (str): The API token for authentication.
        metadata: Optional metadata to pass with the workflow execution.
        extraction_parameters: Optional extraction parameters (e.g., document_type, llm_model).
        classification_parameters: Optional classification parameters (e.g., llm_model).
    """
    execute_api_url = urljoin(config.DOCUMENT_IA_BASE_URL, f"/api/v1/workflows/{workflow_name}/execute")
    files = {"file": (file.name, file.getvalue())}
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }
    
    data = {"metadata": json.dumps(metadata or {"test": "test"})}
    
    # Add extraction parameters if provided
    if extraction_parameters:
        data["extraction-parameters"] = json.dumps(extraction_parameters)
    
    # Add classification parameters if provided
    if classification_parameters:
        data["classification-parameters"] = json.dumps(classification_parameters)
    response = requests.post(
        execute_api_url,
        files=files,
        data=data,
        headers=headers,
        timeout=120,
    )
    print("RESPONSE", response.json())
    return WorkflowExecuteResponse.model_validate(response.json())

def wait_for_execution(execution_id: str, api_token: str) -> ExecutionModel | None:
    """Wait for an execution to complete.

    Args:
        execution_id (str): The UUID of the execution to retrieve.
        api_token (str): The API token for authentication.
    """
    details_api_url = urljoin(config.DOCUMENT_IA_BASE_URL, f"/api/v1/executions/{execution_id}")
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }
    status = ExecutionStatus.STARTED
    execution_details = None

    # TODO: implement max retries
    # TODO: documentation says execution status can be PENDING or DONE
    # but code uses STARTED, SUCCESS, FAILED
    while status == ExecutionStatus.STARTED:
        response = requests.get(
            details_api_url,
            headers=headers,
        )
        if response.status_code == 404:
            # Execution not found in the API
            return None
        elif response.status_code == 200:
            execution_details = ExecutionModel.model_validate(response.json())
            status = execution_details.status
            # Wait before polling again
            time.sleep(1)
        else:
            response.raise_for_status()

    # TODO: `extracted_barcodes` is not under `result` key
    return execution_details