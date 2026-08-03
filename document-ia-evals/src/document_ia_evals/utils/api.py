"""API utilities for document-ia-evals delegating to document-ia-streamlit-common."""

import io
from typing import Any

from document_ia_api.api.contracts.execution.success import ExecutionSuccessModel
from document_ia_api.api.contracts.workflow import WorkflowExecuteResponse

import document_ia_streamlit_common.api as common_api
from document_ia_evals.utils.config import config


def execute_workflow(
    workflow_name: str,
    file: io.BytesIO,
    api_token: str,
    metadata: dict[str, Any] | None = None,
    extraction_parameters: dict[str, Any] | None = None,
    classification_parameters: dict[str, Any] | None = None,
    base_url: str | None = None,
) -> WorkflowExecuteResponse:
    target_base_url = base_url or config.DOCUMENT_IA_BASE_URL
    return common_api.execute_workflow(
        base_url=target_base_url,
        workflow_name=workflow_name,
        file=file,
        api_token=api_token,
        metadata=metadata,
        extraction_parameters=extraction_parameters,
        classification_parameters=classification_parameters,
    )


def wait_for_execution(
    execution_id: str,
    api_token: str,
    base_url: str | None = None,
) -> ExecutionSuccessModel | None:
    target_base_url = base_url or config.DOCUMENT_IA_BASE_URL
    return common_api.wait_for_execution(
        base_url=target_base_url,
        execution_id=execution_id,
        api_token=api_token,
    )


def get_workflows(api_token: str, base_url: str | None = None) -> dict[str, Any]:
    target_base_url = base_url or config.DOCUMENT_IA_BASE_URL
    return common_api.get_workflows(base_url=target_base_url, api_token=api_token)


def execute_workflow_v2(
    workflow_id: str,
    api_token: str,
    file: io.BytesIO | None = None,
    file_url: str | None = None,
    override: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    sync: bool = False,
    base_url: str | None = None,
) -> dict[str, Any]:
    target_base_url = base_url or config.DOCUMENT_IA_BASE_URL
    return common_api.execute_workflow_v2(
        base_url=target_base_url,
        workflow_id=workflow_id,
        api_token=api_token,
        file=file,
        file_url=file_url,
        override=override,
        metadata=metadata,
        sync=sync,
    )
