import json
import streamlit as st
from document_ia_streamlit_common.api import wait_for_execution


def render_retrieve_execution_page(base_url: str, api_key: str):
    title = "🔍 Récupérer une exécution passée"
    st.header(title)

    if not base_url or not api_key:
        st.info("👈 Veuillez sélectionner un environnement et saisir votre clé API dans la barre latérale pour démarrer.")
        return

    st.caption(f"Environnement actif : `{base_url}`")

    execution_id = st.text_input(
        "ID de l'exécution (UUID)",
        placeholder="ex: 123e4567-e89b-12d3-a456-426614174000",
    )

    if st.button("🔍 Récupérer le résultat", type="primary"):
        if not execution_id.strip():
            st.warning("Veuillez saisir un ID d'exécution valide.")
            return

        with st.spinner("Interrogation de l'API Document IA..."):
            try:
                execution_details = wait_for_execution(
                    base_url=base_url,
                    execution_id=execution_id.strip(),
                    api_token=api_key,
                    max_retries=1,  # Single check for retrieval
                )
                if execution_details is None:
                    st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}` ou l'exécution n'est pas terminée.")
                    return

                result_dict = execution_details.model_dump(mode="json")
                st.success("Données de l'exécution récupérées avec succès !")
                st.code(
                    json.dumps(result_dict, indent=2, ensure_ascii=False),
                    language="json",
                )
            except Exception as e:
                st.error(f"Erreur lors de la récupération de l'exécution : {e}")
