import streamlit as st

from document_ia_evals.components import (
    render_document_type_selector,
    render_workflow_selector,
)
from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.components.auth_ui import enforce_page_auth
from document_ia_evals.services.administration_service import get_current_config


def main():
    title = "🧾 Execute a workflow on document (Deprecated)"
    st.set_page_config(page_title=title, page_icon="🧾")
    enforce_page_auth()

    st.title(title)

    cfg = get_current_config()
    endpoint = cfg["base_url"]
    api_key = cfg["api_key"]

    st.caption(f"Using API endpoint: {endpoint}")

    st.warning(
        "⚠️ Cette page est obsolète. Veuillez utiliser la page **Execute Workflow V2** à la place."
    )

    st.markdown(
        "Cette page vous permet de tester rapidement un workflow Document IA sur un document."
    )

    # Workflow selection using component
    workflow_selection = render_workflow_selector()
    if workflow_selection is None:
        return

    # Document type selector (optional, for all workflows)
    selected_doc_type = render_document_type_selector()

    if not api_key:
        st.warning("⚠️ Clé API non configurée pour cette session.")
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

        with st.spinner(
            "Envoie de la requête, en attente de la réponse de l'API...", show_time=True
        ):
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
            st.json(
                execution_details.model_dump(mode="json") if execution_details else None
            )


if __name__ == "__main__":
    main()
