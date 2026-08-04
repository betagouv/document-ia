import io
import json
import time
from typing import Any
from urllib.parse import urljoin

import requests
from document_ia_api.api.contracts.execution.success import ExecutionSuccessModel
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_api.api.contracts.workflow import WorkflowExecuteResponse


def execute_workflow(
    base_url: str,
    workflow_name: str,
    file: io.BytesIO,
    api_token: str,
    metadata: dict[str, Any] | None = None,
    extraction_parameters: dict[str, Any] | None = None,
    classification_parameters: dict[str, Any] | None = None,
) -> WorkflowExecuteResponse:
    """Execute a workflow v1 on the Document IA API.

    Args:
        base_url (str): The base URL of the target environment.
        workflow_name (str): The name of the workflow to execute.
        file: The file-like object to process.
        api_token (str): The API token for authentication.
        metadata: Optional metadata to pass with the workflow execution.
        extraction_parameters: Optional extraction parameters.
        classification_parameters: Optional classification parameters.
    """
    execute_api_url = urljoin(
        base_url, f"/api/v1/workflows/{workflow_name}/execute"
    )
    files = {"file": (file.name, file.getvalue())}
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }

    data = {"metadata": json.dumps(metadata or {"test": "test"})}

    if extraction_parameters:
        data["extraction-parameters"] = json.dumps(extraction_parameters)

    if classification_parameters:
        data["classification-parameters"] = json.dumps(classification_parameters)

    response = requests.post(
        execute_api_url,
        files=files,
        data=data,
        headers=headers,
        timeout=120,
    )
    response.raise_for_status()
    return WorkflowExecuteResponse.model_validate(response.json())


def wait_for_execution(
    base_url: str,
    execution_id: str,
    api_token: str,
    max_retries: int = 120,
    interval_seconds: float = 1.0,
) -> ExecutionSuccessModel | None:
    """Wait for an execution to complete.

    Args:
        base_url (str): The base URL of the target environment.
        execution_id (str): The UUID of the execution to retrieve.
        api_token (str): The API token for authentication.
        max_retries (int): Maximum number of polling retries.
        interval_seconds (float): Polling interval in seconds.
    """
    details_api_url = urljoin(base_url, f"/api/v1/executions/{execution_id}")
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }
    status = ExecutionStatus.STARTED
    execution_details = None

    retries = 0
    while status == ExecutionStatus.STARTED and retries < max_retries:
        response = requests.get(
            details_api_url,
            headers=headers,
            timeout=30,
        )
        response_json = response.json()
        status = response_json.get("status", "")

        if status == ExecutionStatus.SUCCESS:
            execution_details = ExecutionSuccessModel.model_validate(response.json())
            break
        elif status == ExecutionStatus.STARTED:
            time.sleep(interval_seconds)
            retries += 1
        elif status == ExecutionStatus.FAILED:
            execution_details = None
            break
        else:
            response.raise_for_status()

    return execution_details


def get_workflows(base_url: str, api_token: str) -> dict[str, Any]:
    """Retrieve available workflows from Document IA API.

    Args:
        base_url (str): The base URL of the target environment.
        api_token (str): The API token for authentication.
    """
    workflows_url = urljoin(base_url, "/api/v2/workflows")
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }
    response = requests.get(workflows_url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def execute_workflow_v2(
    base_url: str,
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
        base_url (str): The base URL of the target environment.
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
    execute_api_url = urljoin(base_url, path)
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_token,
    }

    files = {}
    if file:
        files["file"] = (getattr(file, "name", "document.pdf"), file.getvalue())

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
