"""Workflow selector smart component."""

import asyncio
import json
from dataclasses import dataclass

import streamlit as st

from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_schemas import SupportedDocumentType


@dataclass
class WorkflowSelection:
    """Result of workflow selection."""
    workflow_id: str
    workflow: object  # Workflow model from repository
    is_fast_workflow: bool


def render_workflow_selector(
    label: str = "Sélectionnez un workflow",
    show_details: bool = True,
    show_fast_warning: bool = True,
) -> WorkflowSelection | None:
    """
    Render workflow selection component with optional details.
    
    This is a smart component that fetches workflows from the repository
    and handles all display logic.
    
    Args:
        label: Label for the selectbox
        show_details: Whether to show workflow details in an expander
        show_fast_warning: Whether to show a warning for non-fast workflows
    
    Returns:
        WorkflowSelection with selected workflow info, or None if no workflows found
    """
    workflows_list = asyncio.run(workflow_repository.get_all_workflows())

    if not workflows_list:
        st.error("❌ No workflows found")
        return None

    # Workflow selector
    workflow_options = {w.id: f"{w.name} (v{w.version})" for w in workflows_list}
    selected_workflow_id = st.selectbox(
        label,
        options=list(workflow_options.keys()),
        format_func=lambda x: workflow_options[x],
        index=0,
    )

    # Get selected workflow
    selected_workflow = next(w for w in workflows_list if w.id == selected_workflow_id)
    
    # Display workflow details
    if show_details:
        with st.expander("Détails du workflow"):
            st.write(f"**Description:** {selected_workflow.description}")
            st.write(f"**Steps:** {', '.join(selected_workflow.steps)}")
            st.write(f"**Model:** {selected_workflow.llm_model}")
            st.write(f"**Supported file types:** {', '.join(selected_workflow.supported_file_types)}")
    
    # Check if fast workflow
    is_fast_workflow = "-fast" in selected_workflow_id or "fast" in selected_workflow_id.lower()

    if show_fast_warning and not is_fast_workflow:
        st.warning("Ce workflow n'est pas un workflow fast. Il est recommandé d'utiliser un workflow fast.")
    
    return WorkflowSelection(
        workflow_id=selected_workflow_id,
        workflow=selected_workflow,
        is_fast_workflow=is_fast_workflow,
    )


def render_extraction_params_info(
    is_fast_workflow: bool,
    document_type: SupportedDocumentType,
) -> None:
    """
    Display extraction parameters info for fast workflows.
    
    Args:
        is_fast_workflow: Whether the workflow is a fast workflow
        document_type: Selected document type
    """
    if is_fast_workflow:
        extraction_params_preview = {"document-type": document_type.value}
        st.info(f"ℹ️ Workflow fast détecté - Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")

