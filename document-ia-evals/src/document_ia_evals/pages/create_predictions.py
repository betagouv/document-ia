# Standard library imports
import asyncio
import json
from typing import Any

# Third-party imports
import streamlit as st

# Local imports
from document_ia_evals.services.create_predictions_service import (
    get_failed_tasks,
    get_processing_statistics,
    get_task_count,
    run_workflow_on_dataset,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import get_label_studio_client
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_schemas import SupportedDocumentType


def render_configuration_warnings() -> bool:
    """
    Check and display warnings for missing configuration.
    
    Returns:
        True if all configuration is valid, False otherwise
    """
    # Check API key
    if not config.DOCUMENT_IA_API_KEY:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return False
    
    # Check S3 configuration
    s3_vars = {
        'S3_ENDPOINT': config.S3_ENDPOINT,
        'S3_ACCESS_KEY': config.S3_ACCESS_KEY,
        'S3_SECRET_KEY': config.S3_SECRET_KEY,
        'S3_BUCKET_NAME': config.S3_BUCKET_NAME,
        'S3_REGION': config.S3_REGION
    }
    missing_s3 = [var for var, val in s3_vars.items() if not val]
    if missing_s3:
        st.warning(f"⚠️ Missing S3 configuration: {', '.join(missing_s3)}")
        return False
    
    return True


def render_workflow_selector() -> tuple[str, Any, bool] | None:
    """
    Render workflow selection and details.
    
    Returns:
        Tuple of (workflow_id, workflow, is_fast_workflow) or None if no workflows
    """
    workflows_list = asyncio.run(workflow_repository.get_all_workflows())
    
    if not workflows_list:
        st.error("❌ No workflows found")
        return None
    
    # Workflow selector
    workflow_options = {w.id: f"{w.name} (v{w.version})" for w in workflows_list}
    selected_workflow_id = st.selectbox(
        "Sélectionnez un workflow",
        options=list(workflow_options.keys()),
        format_func=lambda x: workflow_options[x],
        index=0,
    )
    
    # Display workflow details
    selected_workflow = next(w for w in workflows_list if w.id == selected_workflow_id)
    with st.expander("Détails du workflow"):
        st.write(f"**Description:** {selected_workflow.description}")
        st.write(f"**Steps:** {', '.join(selected_workflow.steps)}")
        st.write(f"**Model:** {selected_workflow.llm_model}")
        st.write(f"**Supported file types:** {', '.join(selected_workflow.supported_file_types)}")
    
    is_fast_workflow = "-fast" in selected_workflow_id or "fast" in selected_workflow_id.lower()
    
    return selected_workflow_id, selected_workflow, is_fast_workflow


def render_document_type_selector(is_fast_workflow: bool) -> SupportedDocumentType:
    """
    Render document type selector.
    
    Args:
        is_fast_workflow: Whether the selected workflow is a fast workflow
    
    Returns:
        Selected document type
    """
    doc_type_options = list(SupportedDocumentType)
    selected_doc_type: SupportedDocumentType = st.selectbox(
        "Type de document (requis pour les workflows fast)",
        options=doc_type_options,
        format_func=lambda x: x.name.replace("_", " ").title(),
        index=0,
        help="Spécifiez le type de document pour les workflows qui n'incluent pas de classification"
    )
    
    # Show extraction parameters info for fast workflows
    if is_fast_workflow:
        extraction_params_preview = {"document-type": selected_doc_type.value}
        st.info(f"ℹ️ Workflow fast détecté - Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")
    
    return selected_doc_type


def render_project_selector(ls_client: Any) -> tuple[int, str] | None:
    """
    Render Label Studio project selector.
    
    Args:
        ls_client: Label Studio client
    
    Returns:
        Tuple of (project_id, project_title) or None if no projects or error
    """
    try:
        projects = ls_client.projects.list()
        
        if not projects:
            st.warning("⚠️ No Label Studio projects found")
            return None
        
        # Project selector
        project_options = {p.id: p.title or f"Project {p.id}" for p in projects}
        selected_project_id: int = st.selectbox(
            "Sélectionnez un dataset Label Studio",
            options=list(project_options.keys()),
            format_func=lambda x: project_options[x],
            index=0,
        )
        
        # Display project details
        selected_project = next(p for p in projects if p.id == selected_project_id)
        with st.expander("Détails du dataset"):
            st.write(f"**Title:** {selected_project.title}")
            st.write(f"**Description:** {selected_project.description or 'N/A'}")
            
            # Get task count
            task_count = get_task_count(ls_client, selected_project_id)
            st.write(f"**Number of tasks:** {task_count}")
        
        return selected_project_id, project_options[selected_project_id]
        
    except Exception as e:
        st.error(f"❌ Failed to fetch Label Studio projects: {e}")
        return None


def render_worker_config() -> int:
    """
    Render worker configuration.
    
    Returns:
        Number of workers
    """
    return st.number_input(
        "Nombre de tâches à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )


def render_model_version_input(default_value: str) -> str:
    """
    Render model version input.
    
    Args:
        default_value: Default value for the input
    
    Returns:
        Model version string
    """
    return st.text_input(
        "Nom de l'annotation (model version)",
        value=default_value,
        help="Nom affiché pour cette annotation dans Label Studio. Par défaut: ID du workflow"
    )


def render_processing_results(results: dict[int, dict[str, Any]]) -> None:
    """
    Render processing results summary and errors.
    
    Args:
        results: Dictionary of task processing results
    """
    success_count, total_count = get_processing_statistics(results)
    st.success(f"✅ {success_count}/{total_count} tâches traitées avec succès")
    
    if success_count < total_count:
        st.warning("⚠️ Certaines tâches n'ont pas pu être traitées:")
        failed_tasks = get_failed_tasks(results)
        for task_id, error, execution_id, processing_time_ms in failed_tasks:
            st.error(f"- Task {task_id}: {error}")
            if execution_id:
                st.info(f"  Execution ID: `{execution_id}`\n Processing Time: `{processing_time_ms}`")


def render_project_link(project_id: int) -> None:
    """
    Render link to Label Studio project.
    
    Args:
        project_id: Label Studio project ID
    """
    project_url = f"{config.LABEL_STUDIO_URL}/projects/{project_id}"
    st.markdown(f"🔗 [Voir les annotations dans Label Studio]({project_url})")


def handle_workflow_execution(
    workflow_id: str,
    workflow_name: str,
    project_id: int,
    project_title: str,
    api_key: str,
    ls_client: Any,
    n_workers: int,
    model_version: str,
    is_fast_workflow: bool,
    selected_doc_type: SupportedDocumentType,
) -> None:
    """
    Handle the workflow execution process.
    
    Args:
        workflow_id: Selected workflow ID
        workflow_name: Workflow display name
        project_id: Label Studio project ID
        project_title: Project display title
        api_key: API key for authentication
        ls_client: Label Studio client
        n_workers: Number of parallel workers
        model_version: Model version for predictions
        is_fast_workflow: Whether workflow is a fast workflow
        selected_doc_type: Selected document type
    """
    # Prepare extraction parameters for fast workflows
    extraction_parameters = None
    if is_fast_workflow:
        extraction_parameters = {"document-type": selected_doc_type.value}
    
    st.info(f"🚀 Exécution du workflow '{workflow_id}' sur le dataset '{project_title}'...")
    
    with st.spinner("Processing tasks...", show_time=True):
        pbar = st.progress(0, text="Executing workflows and creating annotations...")
        
        def update_progress(current: int, total: int) -> None:
            pbar.progress(current / total)
        
        processing_results = run_workflow_on_dataset(
            workflow_id=workflow_id,
            project_id=project_id,
            api_key=api_key,
            ls_client=ls_client,
            n_workers=n_workers,
            model_version=model_version if model_version else None,
            extraction_parameters=extraction_parameters,
            on_progress=update_progress,
        )
    
    # Show results
    if processing_results:
        render_processing_results(processing_results)
        render_project_link(project_id)
        
        # Show detailed results
        with st.expander("Détails des résultats"):
            st.json(processing_results)
    else:
        st.warning("No tasks found in the selected dataset.")


def main() -> None:
    """Main page entry point."""
    title = "Exécuter un workflow sur un dataset"
    st.set_page_config(page_title=title, page_icon="🔄")
    st.title(title)
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )
    
    st.markdown("""
    Cette page vous permet d'exécuter un workflow sur tous les fichiers d'un dataset Label Studio existant :
    1. Sélection du workflow à exécuter
    2. Sélection du dataset Label Studio
    3. Exécution du workflow sur chaque fichier
    4. Création d'une nouvelle annotation avec les résultats
    """)
    
    # Check configuration
    if not render_configuration_warnings():
        return
    
    api_key = config.DOCUMENT_IA_API_KEY
    
    # Get Label Studio client
    ls_client = get_label_studio_client()
    
    # Workflow selection
    workflow_result = render_workflow_selector()
    if workflow_result is None:
        return
    
    selected_workflow_id, selected_workflow, is_fast_workflow = workflow_result
    
    # Document type selector
    selected_doc_type = render_document_type_selector(is_fast_workflow)
    
    # Project selection
    project_result = render_project_selector(ls_client)
    if project_result is None:
        return
    
    selected_project_id, project_title = project_result
    
    # Worker configuration
    n_workers = render_worker_config()
    
    # Model version input
    model_version = render_model_version_input(selected_workflow_id)
    
    # Run workflow button
    if st.button("Lancer l'exécution du workflow", type="primary"):
        handle_workflow_execution(
            workflow_id=selected_workflow_id,
            workflow_name=selected_workflow.name,
            project_id=selected_project_id,
            project_title=project_title,
            api_key=api_key,
            ls_client=ls_client,
            n_workers=n_workers,
            model_version=model_version,
            is_fast_workflow=is_fast_workflow,
            selected_doc_type=selected_doc_type,
        )


if __name__ == "__main__":
    main()
