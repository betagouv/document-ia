import json
import streamlit as st

from document_ia_evals.utils.api import wait_for_execution
from document_ia_evals.utils.config import config


def main():
    title = "🔍 Retrieve results of an execution"
    st.set_page_config(page_title=title, page_icon="🔍")
    st.title(title)

    # Mask base URL to protect sensitive environments
    api_endpoint = config.DOCUMENT_IA_BASE_URL

    st.caption(f"Using API endpoint: {api_endpoint}")

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
            result_dict = execution_details.model_dump() if execution_details else None
            st.code(
                json.dumps(result_dict, indent=2, ensure_ascii=False),
                language="json",
            )


if __name__ == "__main__":
    main()
