"""Shared Streamlit utilities and UI components for Document IA."""

from document_ia_streamlit_common.api import (
    execute_workflow,
    execute_workflow_v2,
    get_workflows,
    wait_for_execution,
)

__all__ = [
    "execute_workflow",
    "execute_workflow_v2",
    "get_workflows",
    "wait_for_execution",
]
