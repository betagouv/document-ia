import streamlit as st

from document_ia_playground.views.execute_workflow import render_execute_workflow_page
from document_ia_playground.views.retrieve_execution import render_retrieve_execution_page
from document_ia_streamlit_common.components import render_sidebar_auth


def main():
    st.set_page_config(
        page_title="Document IA - Playground",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🧪 Document IA — Playground API")
    st.markdown(
        "Bienvenue sur le **Playground Document IA**. Cet outil vous permet de tester en direct l'exécution "
        "des workflows documentaires et de consulter les résultats d'exécutions passées."
    )
    st.write("---")

    # Render global sidebar authentication and environment selection
    base_url, api_key = render_sidebar_auth(
        allow_custom_url=True,
        default_env="🟢 Sandbox",
        key_prefix="playground_",
    )

    # Main Navigation via tabs
    tab_execute, tab_retrieve = st.tabs(
        ["🧾 Exécuter un workflow (v2)", "🔍 Récupérer une exécution"]
    )

    with tab_execute:
        render_execute_workflow_page(base_url, api_key)

    with tab_retrieve:
        render_retrieve_execution_page(base_url, api_key)


if __name__ == "__main__":
    main()
