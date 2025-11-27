import os
import streamlit as st

from document_ia_evals.utils.api import wait_for_execution
from document_ia_evals.utils.config import config

def main():

    title = "Récupération d'ancienne exécution via l'API Document IA"
    st.set_page_config(page_title=title, page_icon="🧾")
    st.title(title)
    st.caption(f"Using API endpoint: {config.DOCUMENT_IA_BASE_URL}")

    api_key = config.DOCUMENT_IA_API_KEY
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return None

    execution_id = st.text_input("ID de l'exécution à récupérer")


    if st.button("Récupérer l'exécution"):
        with st.spinner("Traitement de la réponse...", show_time=True):
            execution_details = wait_for_execution(execution_id, api_key)
            if execution_details is None:
                st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}`.")
                return
            st.json(execution_details)

if __name__ == "__main__":
    main()
