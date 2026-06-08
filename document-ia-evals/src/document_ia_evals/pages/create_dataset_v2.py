# Standard library imports
from typing import Any

# Third-party imports
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

# Local imports
from document_ia_evals.components import render_workflow_configurator
from document_ia_evals.services.create_dataset_service import (
    get_failed_uploads,
    get_upload_statistics,
    process_files_parallel_v2,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import (
    create_label_studio_project,
    create_label_studio_classification_project,
    get_label_studio_client_legacy,
)
from document_ia_schemas import SupportedDocumentType


def update_workflow_doc_type(key_to_update: str, selectbox_key: str):
    """Callback to update workflow configuration state from a selectbox selection."""
    if selectbox_key in st.session_state:
        val = st.session_state[selectbox_key]
        if val:
            st.session_state[key_to_update] = val.value


def render_configuration_warnings() -> bool:
    """Check and display warnings for missing configuration.

    Returns:
        True if all configuration is valid, False otherwise
    """
    # Check API key
    if not config.DOCUMENT_IA_API_KEY:
        st.warning("⚠️ DOCUMENT_IA_API_KEY not found in configuration.")
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

    # Check Label Studio configuration
    if not config.LABEL_STUDIO_URL or not config.LABEL_STUDIO_API_KEY:
        st.warning(
            "⚠️ LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY must be set in configuration"
        )
        return False

    return True


def detect_document_type(
    selected_workflow: dict, override: dict
) -> SupportedDocumentType | None:
    """Detects the document type from workflow settings and overrides."""
    # 1. Check override for "document_type"
    for step_action, params_list in override.items():
        if isinstance(params_list, list):
            for item in params_list:
                if item.get("param") == "document_type" and item.get("value"):
                    val = item.get("value")
                    try:
                        return SupportedDocumentType(val)
                    except ValueError:
                        pass

    # 2. Check workflow default params for "document_type"
    for step in selected_workflow.get("steps", []):
        params = step.get("params", {})
        if "document_type" in params:
            # Check if default is defined
            default_val = params["document_type"].get("default")
            if default_val:
                try:
                    return SupportedDocumentType(default_val)
                except ValueError:
                    pass
            # If no default, check if there is an enum and it has only one value
            enum_vals = params["document_type"].get("enum", [])
            if len(enum_vals) == 1:
                try:
                    return SupportedDocumentType(enum_vals[0])
                except ValueError:
                    pass

    return None


def render_dataset_form(
    selected_doc_type: SupportedDocumentType | None,
    dataset_type: str,
) -> tuple[str, str]:
    """Render dataset configuration form.

    Returns:
        Tuple of (dataset_name, s3_prefix)
    """
    # Dataset name input
    dataset_name = st.text_input(
        "Nom du dataset",
        value="",
        placeholder="ex: tax_notices_batch_1",
        help="Nom unique pour identifier ce dataset",
    )

    dataset_name_clean = dataset_name.strip().strip("/")

    # S3 prefix (computed, read-only)
    if dataset_type == "classification":
        doc_type_segment = "classification"
    else:
        doc_type_segment = (
            selected_doc_type.value.strip("/") if selected_doc_type else "raw"
        )

    s3_prefix = f"{dataset_name_clean}/{doc_type_segment}" if dataset_name_clean else ""
    s3_prefix_display = f"{s3_prefix}/" if s3_prefix else ""

    st.text_input(
        "Préfixe S3",
        value=s3_prefix_display,
        disabled=True,
        help="Chemin où les fichiers seront stockés dans S3 (format: dataset_name/doc_type/)",
    )

    return dataset_name_clean, s3_prefix


def render_file_uploader() -> list[UploadedFile] | None:
    """Render file uploader widget.

    Returns:
        List of uploaded files
    """
    return st.file_uploader(
        "Sélectionnez des fichiers (PDF ou image)",
        accept_multiple_files=True,
        type=["pdf", "jpg", "jpeg", "png"],
    )


def render_worker_config() -> int:
    """Render worker configuration.

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


def render_upload_results(results: dict[str, dict[str, Any]]) -> None:
    """Render upload results summary and errors.

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


def render_label_studio_result(project_info: dict[str, Any]) -> None:
    """Render Label Studio project creation result.

    Args:
        project_info: Dictionary with project information
    """
    st.success("✅ Projet Label Studio créé avec succès!")
    st.json(project_info)

    # Display project link
    label_studio_url = config.LABEL_STUDIO_URL
    project_url = f"{label_studio_url}/projects/{project_info['project_id']}"
    st.markdown(f"🔗 [Ouvrir le projet dans Label Studio]({project_url})")


def handle_dataset_creation_v2(
    dataset_name: str,
    folder: list[UploadedFile] | None,
    workflow_id: str,
    selected_doc_type: SupportedDocumentType | None,
    s3_prefix: str,
    n_workers: int,
    api_key: str,
    override: dict[str, Any] | None = None,
    dataset_type: str = "extraction",
    create_ls_project: bool = True,
    existing_project_id: int | None = None,
    s3_storage_id: int | None = None,
) -> None:
    """Handle the dataset creation or append process using V2 API.

    Args:
        dataset_name: Name for the dataset
        folder: List of uploaded files
        workflow_id: Selected workflow ID
        selected_doc_type: Selected document type (optional)
        s3_prefix: S3 prefix path
        n_workers: Number of parallel workers
        api_key: API key for authentication
        override: Workflow parameter overrides
        dataset_type: Type of dataset ("extraction" or "classification")
        create_ls_project: Whether to create a new Label Studio project
        existing_project_id: Optional ID of an existing Label Studio project to sync instead of creating a new one
        s3_storage_id: Optional ID of the existing project's S3 import storage
    """
    if not existing_project_id and not dataset_name:
        st.warning("⚠️ Veuillez entrer un nom pour le dataset.")
        return

    if not folder:
        st.warning("⚠️ Aucun fichier sélectionné. Veuillez choisir des fichiers.")
        return

    # Step 1: Process files and upload to S3
    st.info(f"📤 Étape 1/2: Traitement de {len(folder)} fichiers et upload vers S3...")

    with st.spinner("Processing files and uploading to S3...", show_time=True):
        pbar = st.progress(0, text="Avancement : 0 / ... fichiers")

        def update_progress(current: int, total: int) -> None:
            pbar.progress(
                current / total if total > 0 else 0.0,
                text=f"Avancement : {current} / {total} fichiers",
            )

        upload_results = process_files_parallel_v2(
            files=folder,
            api_key=api_key,
            workflow_id=workflow_id,
            s3_prefix=s3_prefix,
            n_workers=n_workers,
            override=override,
            metadata={"source": "streamlit-dataset-creation-v2"},
            dataset_type=dataset_type,
            on_progress=update_progress,
        )

    # Show upload results
    render_upload_results(upload_results)

    success_count, _ = get_upload_statistics(upload_results)

    # Step 2: Create or Sync Label Studio project
    if success_count > 0:
        if existing_project_id is not None:
            st.info("📊 Étape 2/2: Synchronisation de l'import storage Label Studio...")
            try:
                ls = get_label_studio_client_legacy()
                project = ls.get_project(existing_project_id)
                storage_to_sync_id = s3_storage_id

                if storage_to_sync_id is None:
                    # Find s3 import storage automatically
                    import_storages = project.get_import_storages()
                    for storage in import_storages:
                        if storage.get("type") == "s3":
                            storage_to_sync_id = storage["id"]
                            break

                if storage_to_sync_id is not None:
                    project.sync_import_storage("s3", storage_to_sync_id)
                    st.success(
                        f"✅ Projet Label Studio (storage ID: {storage_to_sync_id}) synchronisé avec succès !"
                    )
                else:
                    st.error(
                        "❌ Impossible de trouver un import storage S3 dans ce projet pour la synchronisation."
                    )

                label_studio_url = config.LABEL_STUDIO_URL
                project_url = f"{label_studio_url}/projects/{existing_project_id}"
                st.markdown(f"🔗 [Ouvrir le projet dans Label Studio]({project_url})")
            except Exception as e:
                st.error(
                    f"❌ Erreur lors de la synchronisation de l'import storage: {e}"
                )
        elif create_ls_project:
            if dataset_type == "classification":
                st.info(
                    "📊 Étape 2/2: Création du projet de classification Label Studio..."
                )
                try:
                    project_info = create_label_studio_classification_project(
                        dataset_name=dataset_name,
                        s3_prefix=s3_prefix,
                        workflow_id=workflow_id,
                    )
                    render_label_studio_result(project_info)
                except Exception as e:
                    st.error(
                        f"❌ Erreur lors de la création du projet Label Studio: {e}"
                    )
            else:
                if selected_doc_type is None:
                    st.warning(
                        "⚠️ Aucun type de document n'a été sélectionné : "
                        "la création du projet Label Studio est ignorée."
                    )
                else:
                    st.info("📊 Étape 2/2: Création du projet Label Studio...")
                    try:
                        project_info = create_label_studio_project(
                            dataset_name=dataset_name,
                            doc_type=selected_doc_type,
                            s3_prefix=s3_prefix,
                            workflow_id=workflow_id,
                        )
                        render_label_studio_result(project_info)
                    except Exception as e:
                        st.error(
                            f"❌ Erreur lors de la création du projet Label Studio: {e}"
                        )

    # Show detailed results
    with st.expander("Détails des résultats"):
        st.json(upload_results)


def main() -> None:
    """Main page entry point."""
    title = "Création d'un jeu de données terrain V2"
    st.set_page_config(page_title=title, page_icon="📝", layout="wide")
    st.title(title)
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )

    st.markdown(
        """
    Cette page vous permet de créer un nouveau jeu de données pré-annoté avec Label Studio (API V2) ou d'ajouter des documents à un projet existant :
    1. Choisissez le mode d'utilisation (création ou ajout).
    2. Configurez le workflow à exécuter et vos surcharges de paramètres.
    3. Upload des nouveaux fichiers et exécution parallèle des workflows.
    4. Import automatique dans Label Studio (création d'un projet ou synchronisation de l'existant).
    """
    )

    # Check configuration
    if not render_configuration_warnings():
        return

    api_key = config.DOCUMENT_IA_API_KEY
    assert api_key is not None

    # Import selector component
    from document_ia_evals.components.project_selector import (
        ClientType,
        render_project_selector,
    )
    from document_ia_evals.utils.label_studio import (
        extract_project_metadata,
        get_label_studio_client_legacy,
    )

    # 1. Mode Selection
    mode = st.radio(
        "Mode d'utilisation",
        options=[
            "Créer un nouveau dataset",
            "Ajouter des documents à un dataset existant",
        ],
        horizontal=True,
        help="Sélectionnez 'Créer un nouveau dataset' pour générer un nouveau projet Label Studio. Sélectionnez 'Ajouter des documents' pour ajouter des données à un projet existant sans modifier sa configuration.",
    )

    # Configuration variables
    suggested_workflow_id = None
    suggested_doc_type = None
    selected_doc_type = None
    dataset_type = "extraction"
    s3_prefix = ""
    s3_storage_id = None
    project_selection = None

    # Pre-select default workflow IDs for creation mode
    if mode == "Créer un nouveau dataset":
        dataset_type = st.session_state.get(
            "dataset_type_creation_v2", "extraction"
        ).lower()
        suggested_workflow_id = (
            config.DEFAULT_CLASSIFICATION_WORKFLOW_ID
            if dataset_type == "classification"
            else config.DEFAULT_EXTRACTION_WORKFLOW_ID
        )

    # 2. Project Selection for append mode
    if mode == "Ajouter des documents à un dataset existant":
        project_selection = render_project_selector(
            client_type=ClientType.LEGACY,
            label="Sélectionnez le dataset existant",
            show_details=True,
            show_task_count=True,
        )

        if project_selection:
            # Extract metadata
            metadata = extract_project_metadata(project_selection.project_description)
            if metadata:
                dataset_type = metadata.get("dataset_type", "extraction")
                suggested_doc_type = metadata.get("document_type")
                suggested_workflow_id = metadata.get("workflow_id")

                # Resolve document type enum member
                if suggested_doc_type:
                    for opt in SupportedDocumentType:
                        if opt.value == suggested_doc_type:
                            selected_doc_type = opt
                            break

                # Save metadata selection to workflow configuration state
                if selected_doc_type:
                    st.session_state["llm_extract_data_document_type_dataset_v2"] = (
                        selected_doc_type.value
                    )

                st.info(
                    f"ℹ️ Configuration détectée sur le projet existant :\n"
                    f"- **Type de Dataset** : `{dataset_type.title()}`\n"
                    f"- **Type de Document** : `{selected_doc_type.name.replace('_', ' ').title() if selected_doc_type else 'N/A'}`\n"
                    f"- **ID du Workflow original** : `{suggested_workflow_id or 'N/A'}`"
                )
            else:
                st.warning(
                    "⚠️ Aucune métadonnée trouvée sur ce projet. Veuillez configurer manuellement le type de dataset et de document."
                )

                dataset_type = st.selectbox(
                    "Type de Dataset",
                    options=["Extraction", "Classification"],
                    key="dataset_type_append_manual",
                ).lower()

                # Set default workflow ID based on manual dataset type choice
                suggested_workflow_id = (
                    config.DEFAULT_CLASSIFICATION_WORKFLOW_ID
                    if dataset_type == "classification"
                    else config.DEFAULT_EXTRACTION_WORKFLOW_ID
                )

                if dataset_type == "extraction":
                    selected_doc_type = st.selectbox(
                        "Type de document",
                        options=list(SupportedDocumentType),
                        format_func=lambda x: x.name.replace("_", " ").title(),
                        key="doc_type_append_manual",
                        on_change=update_workflow_doc_type,
                        args=(
                            "llm_extract_data_document_type_dataset_v2",
                            "doc_type_append_manual",
                        ),
                    )
                    suggested_doc_type = selected_doc_type.value

            # Retrieve S3 prefix and storage ID from the import storage settings
            try:
                ls = get_label_studio_client_legacy()
                project = ls.get_project(project_selection.project_id)
                import_storages = project.get_import_storages()
                for storage in import_storages:
                    if storage.get("type") == "s3" and storage.get("prefix"):
                        s3_storage_id = storage.get("id")
                        raw_prefix = storage.get("prefix")
                        if raw_prefix.endswith("/tasks"):
                            s3_prefix = raw_prefix[:-6]
                        else:
                            s3_prefix = raw_prefix
                        break
            except Exception as e:
                st.error(
                    f"Erreur lors de la récupération de la configuration S3 du projet : {e}"
                )

            if not s3_prefix:
                # Fallback prefix computation
                project_title_clean = project_selection.project_title.split(" - ")[
                    0
                ].strip()
                if dataset_type == "classification":
                    s3_prefix = f"{project_title_clean}/classification"
                else:
                    s3_prefix = f"{project_title_clean}/{suggested_doc_type or 'raw'}"
                st.warning(
                    f"⚠️ Import storage S3 non trouvé. Préfixe S3 de repli généré : `{s3_prefix}`"
                )
            else:
                st.success(f"📂 Préfixe S3 détecté pour ce projet : `{s3_prefix}`")
        else:
            st.warning("⚠️ Veuillez sélectionner un dataset existant.")
            return

    # Organize interface into Tabs
    tab_files, tab_workflow = st.tabs(
        ["📁 Dataset & Fichiers", "⚙️ Configuration du Workflow"]
    )

    # Render workflow configurator in tab 2
    with tab_workflow:
        selected_workflow, override = render_workflow_configurator(
            api_key,
            key_suffix="_dataset_v2",
            default_workflow_id=suggested_workflow_id,
            default_document_type=suggested_doc_type,
        )

    # Render files uploader and execution button in tab 1
    with tab_files:
        if not selected_workflow:
            st.warning(
                "⚠️ Veuillez sélectionner et configurer un workflow dans l'onglet "
                "'Configuration du Workflow' avant de continuer."
            )
            return

        # Show selected workflow summary
        st.info(
            f"Workflow actif : **{selected_workflow.get('name', selected_workflow.get('id'))}**"
        )

        if mode == "Créer un nouveau dataset":
            # Select Dataset Type
            dataset_type = st.selectbox(
                "Type de Dataset",
                options=["Extraction", "Classification"],
                key="dataset_type_creation_v2",
                help="Sélectionnez 'Classification' si vous souhaitez uniquement étiqueter le type global de document. Sélectionnez 'Extraction' pour extraire des champs de données spécifiques.",
            ).lower()

            # Checkbox to trigger Label Studio project creation
            create_ls_project = st.checkbox(
                "Créer un projet Label Studio",
                value=True,
                help="Cochez cette case pour créer automatiquement un projet d'annotation pré-annoté dans Label Studio.",
            )

            selected_doc_type = None
            if dataset_type == "extraction":
                # Detect document type from workflow configuration
                inferred_doc_type = detect_document_type(selected_workflow, override)

                # Prepare options list
                options = list(SupportedDocumentType)

                # Find default index
                default_index = 0
                if inferred_doc_type in options:
                    default_index = options.index(inferred_doc_type)
                    st.success(
                        f"ℹ️ Type de document détecté automatiquement : **{inferred_doc_type.name.replace('_', ' ').title()}**"
                    )
                else:
                    st.info(
                        "ℹ️ Aucun type de document détecté automatiquement. Veuillez le sélectionner ci-dessous."
                    )

                # Track changes in inferred document type to update selectbox value dynamically
                tracker_inferred_key = "last_inferred_doc_type_creation"
                if inferred_doc_type != st.session_state.get(tracker_inferred_key):
                    st.session_state[tracker_inferred_key] = inferred_doc_type
                    if inferred_doc_type in options:
                        st.session_state["doc_type_creation_selectbox_v2"] = (
                            inferred_doc_type
                        )

                selected_doc_type = st.selectbox(
                    "Type de document",
                    options=options,
                    index=default_index,
                    format_func=lambda x: x.name.replace("_", " ").title(),
                    help="Sélectionnez le type de document pour configurer l'interface Label Studio.",
                    key="doc_type_creation_selectbox_v2",
                    on_change=update_workflow_doc_type,
                    args=(
                        "llm_extract_data_document_type_dataset_v2",
                        "doc_type_creation_selectbox_v2",
                    ),
                )

            # Dataset form
            dataset_name, s3_prefix = render_dataset_form(
                selected_doc_type,
                dataset_type,
            )

            # File uploader
            folder = render_file_uploader()

            # Worker configuration
            n_workers = render_worker_config()

            # Create dataset button
            if st.button("Lancer la création de dataset", type="primary"):
                handle_dataset_creation_v2(
                    dataset_name=dataset_name,
                    folder=folder,
                    workflow_id=selected_workflow["id"],
                    selected_doc_type=selected_doc_type,
                    s3_prefix=s3_prefix,
                    n_workers=n_workers,
                    api_key=api_key,
                    override=override if override else None,
                    dataset_type=dataset_type,
                    create_ls_project=create_ls_project,
                )
        else:
            # Append mode: Configuration is locked, just show details
            st.markdown("### 📋 Configuration de l'Ajout")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Dataset cible :** `{project_selection.project_title}`")
                st.markdown(f"**Type de Dataset :** `{dataset_type.title()}`")
            with col2:
                doc_type_display = (
                    selected_doc_type.name.replace("_", " ").title()
                    if selected_doc_type
                    else "N/A"
                )
                st.markdown(f"**Type de Document :** `{doc_type_display}`")
                st.markdown(f"**Préfixe S3 de destination :** `{s3_prefix}`")

            # File uploader
            folder = render_file_uploader()

            # Worker configuration
            n_workers = render_worker_config()

            # Append button
            if st.button("Lancer l'ajout de documents au dataset", type="primary"):
                handle_dataset_creation_v2(
                    dataset_name=project_selection.project_title,
                    folder=folder,
                    workflow_id=selected_workflow["id"],
                    selected_doc_type=selected_doc_type,
                    s3_prefix=s3_prefix,
                    n_workers=n_workers,
                    api_key=api_key,
                    override=override if override else None,
                    dataset_type=dataset_type,
                    create_ls_project=False,
                    existing_project_id=project_selection.project_id,
                    s3_storage_id=s3_storage_id,
                )


if __name__ == "__main__":
    main()
