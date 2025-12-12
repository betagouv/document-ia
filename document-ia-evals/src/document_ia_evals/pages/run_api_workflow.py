import json

import streamlit as st

from document_ia_evals.components import (
    render_document_type_selector,
    render_workflow_selector,
)
from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.config import config


def main():
    title = "🧾 Execute a workflow on document"
    st.set_page_config(page_title=title, page_icon="🧾")
    st.title(title)
    st.caption(f"Using API endpoint: {config.DOCUMENT_IA_BASE_URL}")

    st.markdown("Cette page vous permet de tester rapidement un workflow Document IA sur un document.")
    
    # Workflow selection using component
    workflow_selection = render_workflow_selector()
    if workflow_selection is None:
        return
    
    # Document type selector (optional, for all workflows)
    selected_doc_type = render_document_type_selector()

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

        # Prepare extraction parameters if document type is provided
        extraction_parameters = None
        if selected_doc_type:
            extraction_parameters = {"document-type": selected_doc_type.value}
        
        # Show request parameters
        with st.expander("📋 Paramètres de la requête", expanded=False):
            request_params = {
                "workflow_name": workflow_selection.workflow_id,
                "extraction_parameters": extraction_parameters,
            }
            st.json(request_params)

        with st.spinner("Envoie de la requête, en attente de la réponse de l'API...", show_time=True):
            workflow_execute_response = execute_workflow(
                workflow_selection.workflow_id,
                uploaded_file,
                api_key,
                extraction_parameters=extraction_parameters,
            )
            execution_id = workflow_execute_response.data.execution_id

        st.info(f"ID de l'exécution : `{execution_id}`")

        with st.spinner("Traitement de la réponse...", show_time=True):
            execution_details = wait_for_execution(execution_id, api_key)
            if execution_details is None:
                st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}`.")
                return
            st.json(execution_details.model_dump() if execution_details else None)

if __name__ == "__main__":
    main()
