import asyncio
import json
import streamlit as st

from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.config import config
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_schemas import SupportedDocumentType

def main():
    title = "Extraction via l'API Document IA"
    st.set_page_config(page_title=title, page_icon="🧾")
    st.title(title)
    st.caption(f"Using API endpoint: {config.DOCUMENT_IA_BASE_URL}")

    st.markdown("Cette page vous permet de tester rapidement un workflow Document IA sur un document.")
    
    # Fetch workflows
    workflows_list = asyncio.run(workflow_repository.get_all_workflows())
    
    if not workflows_list:
        st.error("❌ No workflows found")
        return
    
    # Workflow selector
    workflow_options = {w.id: f"{w.name} (v{w.version})" for w in workflows_list}

    workflow_name = st.selectbox(
        "Sélectionnez le workflow à utiliser",
        options=list(workflow_options.keys()),
        index=0,
    )

    # Display workflow details
    selected_workflow = next(w for w in workflows_list if w.id == workflow_name)
    with st.expander("Détails du workflow"):
        st.write(f"**Description:** {selected_workflow.description}")
        st.write(f"**Steps:** {', '.join(selected_workflow.steps)}")
        st.write(f"**Model:** {selected_workflow.llm_model}")
        st.write(f"**Supported file types:** {', '.join(selected_workflow.supported_file_types)}")

    # Check if it's a fast workflow
    is_fast_workflow = "-fast" in workflow_name or "fast" in workflow_name.lower()
    
    # Document type selector (for fast workflows)
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

    # Metadata input
    default_metadata = json.dumps({"source": "parse_document_page"})
    metadata_str = st.text_input(
        "Métadonnées (JSON)",
        value=default_metadata,
        help="Métadonnées additionnelles à passer au workflow sous forme de JSON"
    )

    # Parse metadata
    try:
        metadata = json.loads(metadata_str) if metadata_str.strip() else {}
    except json.JSONDecodeError:
        st.error("❌ Métadonnées JSON invalides")
        return

    api_key = config.DOCUMENT_IA_API_KEY
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY not found in configuration.")
        return None

    uploaded_file = st.file_uploader(
        "Sélectionnez un document (PDF ou image)",
        type=["pdf", "png", "jpg", "jpeg"],
    )

    if st.button("Lancer l'extraction"):
        if uploaded_file is None:
            st.warning("Veuillez sélectionner un fichier avant de lancer l'extraction.")
            return

        # Prepare extraction parameters for fast workflows
        extraction_parameters = None
        if is_fast_workflow:
            extraction_parameters = {"document-type": selected_doc_type.value}
        
        # Show request parameters
        with st.expander("📋 Paramètres de la requête", expanded=False):
            request_params = {
                "workflow_name": workflow_name,
                "metadata": metadata,
                "extraction_parameters": extraction_parameters,
            }
            st.json(request_params)

        with st.spinner("Envoie de la requête, en attente de la réponse de l'API...", show_time=True):
            workflow_execute_response = execute_workflow(
                workflow_name,
                uploaded_file,
                api_key,
                metadata=metadata,
                extraction_parameters=extraction_parameters,
            )
            execution_id = workflow_execute_response.data.get("execution_id")

        st.info(f"ID de l'exécution : `{execution_id}`")

        with st.spinner("Traitement de la réponse...", show_time=True):
            execution_details = wait_for_execution(execution_id, api_key)
            if execution_details is None:
                st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}`.")
                return
            st.json(execution_details)

if __name__ == "__main__":
    main()