# Standard library imports
from typing import Any

# Third-party imports
import streamlit as st

# Local imports
from document_ia_evals.components import (
    ClientType,
    get_client,
    render_project_selector,
    render_workflow_configurator,
)
from document_ia_evals.services.create_predictions_service import (
    get_failed_tasks,
    get_processing_statistics,
    run_workflow_on_dataset_v2,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import extract_project_metadata


def render_configuration_warnings() -> bool:
    """Check and display warnings for missing configuration.

    Returns:
        True if all configuration is valid, False otherwise
    """
    # Check API key
    if not config.DOCUMENT_IA_API_KEY:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return False

    # Check S3 configuration
    s3_vars = {
        "S3_ENDPOINT": config.S3_ENDPOINT,
        "S3_ACCESS_KEY": config.S3_ACCESS_KEY,
        "S3_SECRET_KEY": config.S3_SECRET_KEY,
        "S3_BUCKET_NAME": config.S3_BUCKET_NAME,
        "S3_REGION": config.S3_REGION,
    }
    missing_s3 = [var for var, val in s3_vars.items() if not val]
    if missing_s3:
        st.warning(f"⚠️ Missing S3 configuration: {', '.join(missing_s3)}")
        return False

    return True


def render_worker_config() -> int:
    """Render worker configuration.

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
    """Render model version input.

    Args:
        default_value: Default value for the input

    Returns:
        Model version string
    """
    return st.text_input(
        "Nom de l'annotation (model version)",
        value=default_value,
        help="Nom affiché pour cette annotation dans Label Studio. Par défaut: ID du workflow",
    )


def render_processing_results(results: dict[int, dict[str, Any]]) -> None:
    """Render processing results summary and errors.

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
                st.info(
                    f"  Execution ID: `{execution_id}`\n Processing Time: `{processing_time_ms} ms`"
                )


def render_project_link(project_id: int) -> None:
    """Render link to Label Studio project.

    Args:
        project_id: Label Studio project ID
    """
    project_url = f"{config.LABEL_STUDIO_URL}/projects/{project_id}"
    st.markdown(f"🔗 [Voir les annotations dans Label Studio]({project_url})")


def detect_document_type(selected_workflow: dict, override: dict) -> str | None:
    """Detects the document type from workflow settings and overrides."""
    # 1. Check override for "document_type"
    for step_action, params_list in override.items():
        if isinstance(params_list, list):
            for item in params_list:
                if item.get("param") == "document_type" and item.get("value"):
                    return item.get("value")

    # 2. Check workflow default params for "document_type"
    for step in selected_workflow.get("steps", []):
        params = step.get("params", {})
        if "document_type" in params:
            # Check if default is defined
            default_val = params["document_type"].get("default")
            if default_val:
                return default_val
            # If no default, check if there is an enum and it has only one value
            enum_vals = params["document_type"].get("enum", [])
            if len(enum_vals) == 1:
                return enum_vals[0]

    return None


def handle_workflow_execution_v2(
    workflow_id: str,
    project_id: int,
    project_title: str,
    api_key: str,
    ls_client: Any,
    n_workers: int,
    model_version: str,
    override: dict[str, Any] | None = None,
    dataset_type: str = "extraction",
) -> None:
    """Handle the workflow execution process using V2 API.

    Args:
        workflow_id: Selected workflow ID
        project_id: Label Studio project ID
        project_title: Project display title
        api_key: API key for authentication
        ls_client: Label Studio client
        n_workers: Number of parallel workers
        model_version: Model version for predictions
        override: Workflow parameter overrides
        dataset_type: Type of dataset ("extraction" or "classification")
    """
    st.info(
        f"🚀 Exécution du workflow '{workflow_id}' sur le dataset '{project_title}'..."
    )

    with st.spinner("Processing tasks...", show_time=True):
        pbar = st.progress(0, text="Avancement : 0 / ... fichiers")

        def update_progress(current: int, total: int) -> None:
            pbar.progress(
                current / total if total > 0 else 0.0,
                text=f"Avancement : {current} / {total} fichiers",
            )

        processing_results = run_workflow_on_dataset_v2(
            workflow_id=workflow_id,
            project_id=project_id,
            api_key=api_key,
            ls_client=ls_client,
            n_workers=n_workers,
            model_version=model_version if model_version else None,
            override=override,
            dataset_type=dataset_type,
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
    title = "Exécuter un workflow sur un dataset V2"
    st.set_page_config(page_title=title, page_icon="🔄", layout="wide")
    st.title(title)
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )

    st.markdown(
        """
    Cette page vous permet d'exécuter un workflow V2 sur tous les fichiers d'un dataset Label Studio existant :
    1. Sélection et configuration du workflow à exécuter (surcharges de paramètres)
    2. Sélection du dataset Label Studio
    3. Exécution du workflow V2 sur chaque fichier avec vos configurations
    4. Création d'une nouvelle prédiction avec les résultats
    """
    )

    # Check configuration
    if not render_configuration_warnings():
        return

    api_key = config.DOCUMENT_IA_API_KEY
    assert api_key is not None

    # Organize interface into Tabs
    tab_files, tab_workflow = st.tabs(
        ["📁 Dataset & Prédictions", "⚙️ Configuration du Workflow"]
    )

    suggested_workflow_id = None
    suggested_doc_type = None
    project_selection = None
    metadata = None

    # Render files selector and execution in tab 1 (Part 1)
    with tab_files:
        st.subheader("📁 Sélection du Dataset Label Studio")

        # Project selection using component (SDK client)
        project_selection = render_project_selector(
            client_type=ClientType.SDK,
            label="Sélectionnez un dataset Label Studio",
            show_details=True,
            show_task_count=True,
        )

        # Extract metadata from project selection
        if project_selection:
            metadata = extract_project_metadata(project_selection.project_description)
            if metadata:
                suggested_workflow_id = metadata.get("workflow_id")
                suggested_doc_type = metadata.get("document_type")

                # Auto-suggest dataset type
                suggested_type = metadata.get("dataset_type", "").title()
                if suggested_type in ["Extraction", "Classification"]:
                    tracker_dt_key = "last_suggested_dataset_type_predictions_v2"
                    if suggested_type != st.session_state.get(tracker_dt_key):
                        st.session_state[tracker_dt_key] = suggested_type
                        st.session_state["dataset_type_predictions_v2"] = suggested_type

        # Select Dataset Type
        dataset_type = st.selectbox(
            "Type de Dataset",
            options=["Extraction", "Classification"],
            key="dataset_type_predictions_v2",
            help="Sélectionnez 'Classification' si le dataset ne contient que des types de document à étiqueter. Sélectionnez 'Extraction' pour extraire des champs de données spécifiques.",
        ).lower()

        # Worker configuration
        n_workers = render_worker_config()

    # Render workflow configurator in tab 2
    with tab_workflow:
        selected_workflow, override = render_workflow_configurator(
            api_key,
            key_suffix="_predictions_v2",
            default_workflow_id=suggested_workflow_id,
            default_document_type=suggested_doc_type,
        )

    # Continue rendering execution controls in tab 1 (Part 2)
    with tab_files:
        if not selected_workflow:
            st.warning(
                "⚠️ Veuillez sélectionner et configurer un workflow dans l'onglet "
                "'Configuration du Workflow' avant de continuer."
            )
            return

        st.write("---")
        st.subheader("🚀 Exécution des Prédictions")

        # Show selected workflow summary
        st.info(
            f"Workflow actif : **{selected_workflow.get('name', selected_workflow.get('id'))}**"
        )

        # Warnings and Compatibility checks
        if metadata:
            # Check dataset type compatibility
            project_dataset_type = metadata.get("dataset_type")
            if project_dataset_type and project_dataset_type != dataset_type:
                st.warning(
                    f"⚠️ **Incompatibilité de Type de Dataset** : Ce dataset a été créé en mode "
                    f"**{project_dataset_type.title()}**, mais vous exécutez actuellement en mode "
                    f"**{dataset_type.title()}**."
                )

            # Check document type compatibility for extraction datasets
            if dataset_type == "extraction":
                project_doc_type = metadata.get("document_type")
                if project_doc_type:
                    workflow_doc_type = detect_document_type(
                        selected_workflow, override
                    )
                    if workflow_doc_type and workflow_doc_type != project_doc_type:
                        st.warning(
                            f"⚠️ **Incompatibilité de Type de Document** : Ce dataset est configuré pour le type de document "
                            f"**{project_doc_type.upper()}**, mais le workflow sélectionné semble configuré pour "
                            f"**{workflow_doc_type.upper()}**."
                        )

        # Model version input
        model_version = render_model_version_input(selected_workflow["id"])

        # Run workflow button
        if st.button("Lancer l'exécution du workflow V2", type="primary"):
            if project_selection is None:
                st.warning(
                    "⚠️ Veuillez sélectionner un dataset Label Studio avant de lancer l'exécution."
                )
            else:
                # Get the client for later use
                ls_client = get_client(ClientType.SDK)
                handle_workflow_execution_v2(
                    workflow_id=selected_workflow["id"],
                    project_id=project_selection.project_id,
                    project_title=project_selection.project_title,
                    api_key=api_key,
                    ls_client=ls_client,
                    n_workers=n_workers,
                    model_version=model_version,
                    override=override if override else None,
                    dataset_type=dataset_type,
                )


if __name__ == "__main__":
    main()
