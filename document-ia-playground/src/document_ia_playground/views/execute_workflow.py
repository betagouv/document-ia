import json
import streamlit as st

from document_ia_streamlit_common.api import execute_workflow_v2, wait_for_execution
from document_ia_streamlit_common.components import render_workflow_configurator
from document_ia_streamlit_common.snippets import generate_code_snippets


def render_execute_workflow_page(base_url: str, api_key: str):
    title = "🧾 Exécuter un workflow v2"
    st.header(title)

    if not base_url or not api_key:
        st.info("👈 Veuillez sélectionner un environnement et saisir votre clé API dans la barre latérale pour démarrer.")
        return

    st.caption(f"Environnement actif : `{base_url}`")

    # Render reusable workflow configurator component
    selected_workflow, override = render_workflow_configurator(
        base_url=base_url,
        api_key=api_key,
        key_suffix="_playground",
    )

    if not selected_workflow:
        return

    # Document inputs & parameters
    st.write("---")
    st.subheader("📤 Paramètres de la requête")

    input_method = st.radio(
        "Source du document",
        options=["Téléverser un fichier local", "URL du document"],
        horizontal=True,
    )

    uploaded_file = None
    file_url = None

    if input_method == "Téléverser un fichier local":
        uploaded_file = st.file_uploader(
            "Sélectionnez un document (PDF ou image)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=False,
        )
    else:
        file_url = st.text_input(
            "URL du document (PDF ou image)",
            placeholder="https://example.com/document.pdf",
        )

    col_mode, col_meta = st.columns(2)
    with col_mode:
        sync_mode = st.toggle(
            "Mode synchrone (attente directe de la réponse)", value=False
        )
    with col_meta:
        metadata_input = st.text_input(
            "Métadonnées (JSON optionnel)",
            value='{"source": "document-ia-playground"}',
        )

    # Parse metadata JSON
    metadata = {}
    if metadata_input:
        try:
            metadata = json.loads(metadata_input)
        except json.JSONDecodeError:
            st.error("Le JSON des métadonnées est invalide.")
            return

    # Preview generated override JSON
    if override:
        st.write("---")
        st.subheader("📋 Surcharges générées (Override JSON)")
        st.json(override)

    # Dynamic Code Snippets Generation
    st.write("---")
    st.subheader("💻 Exemples d'intégration")

    snippets = generate_code_snippets(
        base_url=base_url,
        workflow_id=selected_workflow["id"],
        sync_mode=sync_mode,
        input_method=input_method,
        file_url=file_url,
        override=override if override else None,
        metadata=metadata if metadata else None,
        api_key_placeholder="VOTRE_CLE_API",
    )

    tab_curl, tab_py, tab_ts, tab_java = st.tabs(["cURL", "Python (requests)", "TypeScript", "Java (OkHttp)"])
    with tab_curl:
        st.code(snippets["bash"], language="bash")
    with tab_py:
        st.code(snippets["python"], language="python")
    with tab_ts:
        st.code(snippets["typescript"], language="typescript")
    with tab_java:
        st.code(snippets["java"], language="java")

    # Execution Action Button
    st.write("---")
    if st.button("🚀 Lancer l'exécution du workflow", type="primary"):
        if input_method == "Téléverser un fichier local" and uploaded_file is None:
            st.warning("Veuillez sélectionner un fichier avant de lancer l'extraction.")
            return
        elif input_method == "URL du document" and not file_url:
            st.warning("Veuillez saisir une URL valide avant de lancer l'extraction.")
            return

        with st.spinner("Envoi de la requête à l'API..."):
            try:
                response = execute_workflow_v2(
                    base_url=base_url,
                    workflow_id=selected_workflow["id"],
                    api_token=api_key,
                    file=uploaded_file,
                    file_url=file_url if input_method == "URL du document" else None,
                    override=override if override else None,
                    metadata=metadata if metadata else None,
                    sync=sync_mode,
                )
            except Exception as e:
                st.error(f"❌ Erreur lors de l'exécution : {e}")
                return

        st.success("✅ Requête envoyée avec succès !")

        if sync_mode:
            st.subheader("Résultat de l'exécution (Synchrone)")
            st.code(
                json.dumps(response, indent=2, ensure_ascii=False),
                language="json",
            )
        else:
            execution_id = response.get("execution_id") or response.get("data", {}).get(
                "execution_id"
            )
            if not execution_id:
                st.error("Aucun ID d'exécution renvoyé par l'API.")
                st.code(
                    json.dumps(response, indent=2, ensure_ascii=False),
                    language="json",
                )
                return

            st.info(f"🆔 **ID de l'exécution :** `{execution_id}`")

            with st.spinner("Attente du traitement du document..."):
                execution_details = wait_for_execution(
                    base_url=base_url,
                    execution_id=execution_id,
                    api_token=api_key,
                )
                if execution_details is None:
                    st.error(f"Aucune exécution ou statut invalide pour l'ID `{execution_id}`.")
                    return
                st.subheader("Résultat final de l'exécution")
                result_dict = execution_details.model_dump(mode="json")
                st.code(
                    json.dumps(result_dict, indent=2, ensure_ascii=False),
                    language="json",
                )
