import os
import streamlit as st

from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.config import Config

def main():
    title = "Extraction via l'API Document IA"
    st.set_page_config(page_title=title, page_icon="🧾")
    st.title(title)
    st.caption(f"Using API endpoint: {Config.BASE_URL}")

    st.markdown("Cette page vous permet de tester rapidement un workflow Document IA sur un document.")

    workflow_name = st.selectbox(
        "Sélectionnez le workflow à utiliser",
        options=["document-extraction-v1", "document-classification-v1"],
        index=0,
    )

    api_key = os.getenv("DOCUMENT_IA_API_KEY")
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return None

    uploaded_file = st.file_uploader(
        "Sélectionnez un document (PDF ou image)",
        type=["pdf", "png", "jpg", "jpeg"],
    )

    if st.button("Lancer l'extraction"):
        if uploaded_file is None:
            st.warning("Veuillez sélectionner un fichier avant de lancer l'extraction.")
            return

        with st.spinner("Envoie de la requête, en attente de la réponse de l'API...", show_time=True):
            workflow_execute_response = execute_workflow(
                workflow_name,
                uploaded_file,
                api_key,
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