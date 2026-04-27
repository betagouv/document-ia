# Standard library imports
from typing import Any

# Third-party imports
import streamlit as st

# Local imports
from document_ia_evals.components import (
    ClientType,
    get_client,
    render_document_type_selector,
    render_project_selector,
    render_workflow_selector,
)
from document_ia_evals.services.create_predictions_service import (
    get_failed_tasks,
    get_processing_statistics,
    run_workflow_on_dataset,
)
from document_ia_evals.utils.config import config
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
    project_id: int,
    project_title: str,
    api_key: str,
    ls_client: Any,
    n_workers: int,
    model_version: str,
    selected_doc_type: SupportedDocumentType | None,
    mode: str = "extraction",
) -> None:
    """
    Handle the workflow execution process.

    Args:
        workflow_id: Selected workflow ID
        project_id: Label Studio project ID
        project_title: Project display title
        api_key: API key for authentication
        ls_client: Label Studio client
        n_workers: Number of parallel workers
        model_version: Model version for predictions
        selected_doc_type: Selected document type (optional)
    """
    # Prepare extraction parameters if document type is provided
    extraction_parameters = None
    if selected_doc_type:
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
            mode=mode,
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

    # Workflow selection using component
    workflow_selection = render_workflow_selector()
    if workflow_selection is None:
        return

    # Mode selection
    mode_selection = st.radio(
        "Mode de traitement",
        options=["Extraction", "Classification"],
        help="Extraction: extrait des champs spécifiques. Classification: identifie le type de document.",
        horizontal=True
    )
    mode = "classification" if mode_selection == "Classification" else "extraction"

    # Document type selector (optional, for all workflows)
    selected_doc_type = render_document_type_selector()

    # Project selection using component (SDK client)
    project_selection = render_project_selector(
        client_type=ClientType.SDK,
        label="Sélectionnez un dataset Label Studio",
        show_details=True,
        show_task_count=True,
    )
    if project_selection is None:
        return

    # Get the client for later use
    ls_client = get_client(ClientType.SDK)

    # Worker configuration
    n_workers = render_worker_config()

    # Model version input
    model_version = render_model_version_input(workflow_selection.workflow_id)

    # Run workflow button
    if st.button("Lancer l'exécution du workflow", type="primary"):
        handle_workflow_execution(
            workflow_id=workflow_selection.workflow_id,
            project_id=project_selection.project_id,
            project_title=project_selection.project_title,
            api_key=api_key,
            ls_client=ls_client,
            n_workers=n_workers,
            model_version=model_version,
            selected_doc_type=selected_doc_type,
            mode=mode,
        )


if __name__ == "__main__":
    main()
