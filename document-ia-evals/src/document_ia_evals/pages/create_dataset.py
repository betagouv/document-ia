# Standard library imports
import asyncio
import json

# Third-party imports
import streamlit as st

# Local imports
from document_ia_evals.services.dataset_service import (
    get_failed_uploads,
    get_upload_statistics,
    process_files_parallel,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import create_label_studio_project
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
        st.warning("⚠️ DOCUMENT_IA_API_KEY not found in configuration.")
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
    
    # Check Label Studio configuration
    if not config.LABEL_STUDIO_URL or not config.LABEL_STUDIO_API_KEY:
        st.warning("⚠️ LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY must be set in configuration")
        return False
    
    return True


def render_workflow_selector() -> tuple[str, dict, bool] | None:
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

    if not is_fast_workflow:
        st.warning("Ce workflow n'est pas un workflow fast. Il est recommandé de créer un dataset avec un workflow fast.")
    
    return selected_workflow_id, selected_workflow, is_fast_workflow


def render_dataset_form(is_fast_workflow: bool) -> tuple[str, SupportedDocumentType, str]:
    """
    Render dataset configuration form.
    
    Args:
        is_fast_workflow: Whether the selected workflow is a fast workflow
    
    Returns:
        Tuple of (dataset_name, document_type, s3_prefix)
    """
    # Dataset name input
    dataset_name = st.text_input(
        "Nom du dataset",
        value="",
        placeholder="ex: tax_notices_batch_1",
        help="Nom unique pour identifier ce dataset"
    )

    # Document type selector
    doc_type_options = list(SupportedDocumentType)
    selected_doc_type: SupportedDocumentType = st.selectbox(
        "Type de document",
        options=doc_type_options,
        format_func=lambda x: x.name.replace("_", " ").title(),
        index=0,
    )
    
    # Show extraction parameters info for fast workflows
    if is_fast_workflow:
        extraction_params_preview = {"document-type": selected_doc_type.value}
        st.info(f"ℹ️ Workflow fast détecté - Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")

    # S3 prefix (computed, read-only)
    s3_prefix = f"{dataset_name}_{selected_doc_type.value}" if dataset_name else ""
    st.text_input(
        "Préfixe S3",
        value=s3_prefix,
        disabled=True,
        help="Chemin où les fichiers seront stockés dans S3"
    )
    
    return dataset_name, selected_doc_type, s3_prefix


def render_file_uploader():
    """
    Render file uploader widget.
    
    Returns:
        List of uploaded files
    """
    return st.file_uploader(
        "Sélectionnez des fichiers (PDF ou image)",
        accept_multiple_files=True,
        type=['pdf', 'jpg', 'jpeg', 'png']
    )


def render_worker_config() -> int:
    """
    Render worker configuration.
    
    Returns:
        Number of workers
    """
    return st.number_input(
        "Nombre de documents à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )


def render_upload_results(results: dict) -> None:
    """
    Render upload results summary and errors.
    
    Args:
        results: Dictionary of file processing results
    """
    success_count, total_count = get_upload_statistics(results)
    st.success(f"✅ {success_count}/{total_count} fichiers traités avec succès")
    
    if success_count < total_count:
        st.warning("⚠️ Certains fichiers n'ont pas pu être traités:")
        failed_uploads = get_failed_uploads(results)
        for name, error, execution_id in failed_uploads:
            st.error(f"- {name}: {error}")
            if execution_id:
                st.info(f"  Execution ID: `{execution_id}`")


def render_label_studio_result(project_info: dict) -> None:
    """
    Render Label Studio project creation result.
    
    Args:
        project_info: Dictionary with project information
    """
    st.success("✅ Projet Label Studio créé avec succès!")
    st.json(project_info)
    
    # Display project link
    label_studio_url = config.LABEL_STUDIO_URL
    project_url = f"{label_studio_url}/projects/{project_info['project_id']}"
    st.markdown(f"🔗 [Ouvrir le projet dans Label Studio]({project_url})")


def handle_dataset_creation(
    dataset_name: str,
    folder: list,
    workflow_id: str,
    selected_doc_type: SupportedDocumentType,
    s3_prefix: str,
    n_workers: int,
    api_key: str,
    is_fast_workflow: bool,
) -> None:
    """
    Handle the dataset creation process.
    
    Args:
        dataset_name: Name for the dataset
        folder: List of uploaded files
        workflow_id: Selected workflow ID
        selected_doc_type: Selected document type
        s3_prefix: S3 prefix path
        n_workers: Number of parallel workers
        api_key: API key for authentication
        is_fast_workflow: Whether workflow is a fast workflow
    """
    if not dataset_name:
        st.warning("⚠️ Veuillez entrer un nom pour le dataset.")
        return
    
    if not folder:
        st.warning("⚠️ Aucun fichier sélectionné. Veuillez choisir des fichiers.")
        return
    
    # Step 1: Process files and upload to S3
    st.info(f"📤 Étape 1/2: Traitement de {len(folder)} fichiers et upload vers S3...")
    
    with st.spinner("Processing files and uploading to S3...", show_time=True):
        pbar = st.progress(0, text="Executing workflows and uploading...")
        
        def update_progress(current: int, total: int) -> None:
            pbar.progress(current / total)
        
        upload_results = process_files_parallel(
            files=folder,
            api_key=api_key,
            workflow_id=workflow_id,
            s3_prefix=s3_prefix,
            n_workers=n_workers,
            document_type=selected_doc_type,
            is_fast_workflow=is_fast_workflow,
            on_progress=update_progress,
        )
    
    # Show upload results
    render_upload_results(upload_results)
    
    success_count, _ = get_upload_statistics(upload_results)
    
    # Step 2: Create Label Studio project
    if success_count > 0:
        st.info("📊 Étape 2/2: Création du projet Label Studio...")
        try:
            project_info = create_label_studio_project(
                dataset_name=dataset_name,
                doc_type=selected_doc_type,
                s3_prefix=s3_prefix
            )
            render_label_studio_result(project_info)
        except Exception as e:
            st.error(f"❌ Erreur lors de la création du projet Label Studio: {e}")
    
    # Show detailed results
    with st.expander("Détails des résultats"):
        st.json(upload_results)


def main() -> None:
    """Main page entry point."""
    title = "Création d'un jeu de données terrain"
    st.set_page_config(page_title=title, page_icon="📝")
    st.title(title)
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )
    
    st.markdown("""
    Cette page vous permet de créer un jeu de données pré-annoté avec Label Studio :
    1. Upload de fichiers et exécution du workflow pour obtenir les annotations de référence
    2. Upload vers S3 au format Label Studio
    3. Création automatique du projet Label Studio
    """)
    
    # Check configuration
    if not render_configuration_warnings():
        return
    
    api_key = config.DOCUMENT_IA_API_KEY
    
    # Workflow selection
    workflow_result = render_workflow_selector()
    if workflow_result is None:
        return
    
    selected_workflow_id, _, is_fast_workflow = workflow_result

    # Dataset form
    dataset_name, selected_doc_type, s3_prefix = render_dataset_form(is_fast_workflow)
    
    # File uploader
    folder = render_file_uploader()
    
    # Worker configuration
    n_workers = render_worker_config()
    
    # Create dataset button
    if st.button("Lancer la création de dataset", type="primary"):
        handle_dataset_creation(
            dataset_name=dataset_name,
            folder=folder,
            workflow_id=selected_workflow_id,
            selected_doc_type=selected_doc_type,
            s3_prefix=s3_prefix,
            n_workers=n_workers,
            api_key=api_key,
            is_fast_workflow=is_fast_workflow,
        )


if __name__ == "__main__":
    main()
