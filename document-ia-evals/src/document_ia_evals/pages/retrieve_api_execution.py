import json
import streamlit as st

from document_ia_evals.components.auth_ui import enforce_page_auth
from document_ia_evals.services.administration_service import get_current_config
from document_ia_evals.utils.api import wait_for_execution


def main():
    title = "🔍 Retrieve results of an execution"
    st.set_page_config(page_title=title, page_icon="🔍")
    enforce_page_auth()

    st.title(title)

    cfg = get_current_config()
    api_endpoint = cfg["base_url"]
    api_key = cfg["api_key"]

    st.caption(f"Using API endpoint: {api_endpoint}")

    if not api_key:
        st.warning("⚠️ Clé API non configurée pour cette session.")
        return None

    execution_id = st.text_input("ID de l'exécution à récupérer")

    if st.button("Récupérer l'exécution"):
        with st.spinner("Traitement de la réponse...", show_time=True):
            execution_details = wait_for_execution(execution_id, api_key)
            if execution_details is None:
                st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}`.")
                return
            result_dict = (
                execution_details.model_dump(mode="json") if execution_details else None
            )
            st.code(
                json.dumps(result_dict, indent=2, ensure_ascii=False),
                language="json",
            )


if __name__ == "__main__":
    main()
