import io
import time
import json
from typing import Any
from urllib.parse import urljoin

from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_api.api.contracts.execution.success import ExecutionSuccessModel
from document_ia_api.api.contracts.workflow import WorkflowExecuteResponse
import requests

from document_ia_evals.utils.config import config


def execute_workflow(
    workflow_name: str,
    file: io.BytesIO,
    api_token: str,
    metadata: dict[str, Any] | None = None,
    extraction_parameters: dict[str, Any] | None = None,
    classification_parameters: dict[str, Any] | None = None,
) -> WorkflowExecuteResponse:
    """ "Execute a workflow on the Document IA API.

    Args:
        workflow_name (str): The name of the workflow to execute.
        file: The file-like object to process.
        api_token (str): The API token for authentication.
        metadata: Optional metadata to pass with the workflow execution.
        extraction_parameters: Optional extraction parameters (e.g., document_type, llm_model).
        classification_parameters: Optional classification parameters (e.g., llm_model).
    """
    execute_api_url = urljoin(
        config.DOCUMENT_IA_BASE_URL, f"/api/v1/workflows/{workflow_name}/execute"
    )
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


def wait_for_execution(
    execution_id: str, api_token: str
) -> ExecutionSuccessModel | None:
    """Wait for an execution to complete.

    Args:
        execution_id (str): The UUID of the execution to retrieve.
        api_token (str): The API token for authentication.
    """
    details_api_url = urljoin(
        config.DOCUMENT_IA_BASE_URL, f"/api/v1/executions/{execution_id}"
    )
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
        response_json = response.json()
        status = response_json.get("status", "")

        if status == ExecutionStatus.SUCCESS:
            execution_details = ExecutionSuccessModel.model_validate(response.json())
        elif status == ExecutionStatus.STARTED:
            time.sleep(1)
        elif status == ExecutionStatus.FAILED:
            execution_details = None
        else:
            response.raise_for_status()

    # TODO: `extracted_barcodes` is not under `result` key
    return execution_details


def get_workflows(api_token: str) -> dict[str, Any]:
    """Retrieve available workflows from Document IA API.

    Args:
        api_token (str): The API token for authentication.
    """
    workflows_url = urljoin(config.DOCUMENT_IA_BASE_URL, "/api/v2/workflows")
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }
    response = requests.get(workflows_url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def execute_workflow_v2(
    workflow_id: str,
    api_token: str,
    file: io.BytesIO | None = None,
    file_url: str | None = None,
    override: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    sync: bool = False,
) -> dict[str, Any]:
    """Execute a workflow v2 on the Document IA API.

    Args:
        workflow_id (str): The ID of the workflow to execute.
        api_token (str): The API token for authentication.
        file: Optional file-like object to process.
        file_url: Optional URL of the file to process.
        override: Optional parameter overrides for the workflow steps.
        metadata: Optional metadata to pass with the workflow execution.
        sync: Whether to run synchronously or asynchronously.
    """
    path = (
        f"/api/v2/workflows/{workflow_id}/execute-sync"
        if sync
        else f"/api/v2/workflows/{workflow_id}/execute"
    )
    execute_api_url = urljoin(config.DOCUMENT_IA_BASE_URL, path)
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }

    files = {}
    if file:
        files["file"] = (file.name, file.getvalue())

    data = {}
    if file_url:
        data["file_url"] = file_url
    if metadata:
        data["metadata"] = json.dumps(metadata)
    if override:
        data["override"] = json.dumps(override)

    response = requests.post(
        execute_api_url,
        files=files if files else None,
        data=data,
        headers=headers,
        timeout=180,
    )
    response.raise_for_status()
    return response.json()
