import json
import pathlib
import streamlit as st

from document_ia_evals.components import render_workflow_configurator
from document_ia_evals.utils.api import (
    execute_workflow_v2,
    wait_for_execution,
)
from document_ia_evals.utils.config import config


def load_snippet(filename: str) -> str:
    path = pathlib.Path(__file__).parent.parent / "assets" / "snippets" / filename
    return path.read_text(encoding="utf-8")



def main():
    title = "🧾 Execute a workflow on document"
    st.set_page_config(page_title=title, page_icon="🧾")
    st.title(title)

    # Mask base URL to protect sensitive environments
    masked_url = config.DOCUMENT_IA_BASE_URL
    if "localhost" not in masked_url and "127.0.0.1" not in masked_url:
        masked_url = "https://<DOCUMENT_IA_URL>/"

    st.caption(f"Using API endpoint: {masked_url}")

    # Check for API Key
    api_key = config.DOCUMENT_IA_API_KEY
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY not found in configuration.")
        return

    # Render reusable workflow configurator
    selected_workflow, override = render_workflow_configurator(
        api_key, key_suffix="_playground"
    )

    if not selected_workflow:
        return

    # Document inputs, metadata & sync/async configuration
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
            "Mode synchrone (attente de la réponse de l'API)", value=False
        )
    with col_meta:
        metadata_input = st.text_input(
            "Métadonnées (JSON optionnel)",
            value='{"source": "streamlit-playground"}',
        )

    # Parse metadata
    metadata = {}
    if metadata_input:
        try:
            metadata = json.loads(metadata_input)
        except json.JSONDecodeError:
            st.error("Le JSON des métadonnées est invalide.")
            return

    # Preview generated override JSON
    st.write("---")
    st.subheader("📋 Surcharges générées (Override JSON)")
    st.json(override)

    # Dynamic Code Snippets Generation
    st.write("---")
    st.subheader("💻 Exemples d'intégration (Code Snippets)")

    # Calculate variables for snippets
    base_url = config.DOCUMENT_IA_BASE_URL.rstrip("/")
    if "localhost" not in base_url and "127.0.0.1" not in base_url:
        base_url = "https://<DOCUMENT_IA_URL>"

    workflow_id = selected_workflow["id"]
    endpoint_path = (
        "/api/v2/workflows/{}/execute-sync"
        if sync_mode
        else "/api/v2/workflows/{}/execute"
    )
    full_url = f"{base_url}{endpoint_path.format(workflow_id)}"
    api_key_str = "<DOCUMENT_IA_API_KEY>"

    override_json_str = json.dumps(override, ensure_ascii=False) if override else "{}"
    metadata_json_str = json.dumps(metadata, ensure_ascii=False) if metadata else "{}"

    override_escaped_java = override_json_str.replace('"', '\\"')
    metadata_escaped_java = metadata_json_str.replace('"', '\\"')

    doc_url = file_url if file_url else "https://example.com/document.pdf"

    tab_curl, tab_ts, tab_java = st.tabs(["cURL", "TypeScript", "Java (OkHttp)"])

    with tab_curl:
        curl_template = load_snippet("example.sh")
        curl_file = (
            '-F "file=@/chemin/vers/votre/fichier.pdf"'
            if input_method == "Téléverser un fichier local"
            else f'-F "file_url={doc_url}"'
        )

        if override:
            curl_template = curl_template.replace(
                "OVERRIDE_CODE_PLACEHOLDER",
                f"-F 'override={override_json_str}'"
            )
        else:
            curl_template = curl_template.replace("  OVERRIDE_CODE_PLACEHOLDER \\\n", "")

        if metadata:
            curl_template = curl_template.replace(
                "METADATA_CODE_PLACEHOLDER",
                f"-F 'metadata={metadata_json_str}'"
            )
        else:
            curl_template = curl_template.replace("  METADATA_CODE_PLACEHOLDER \\\n", "")

        curl_code = (
            curl_template.replace("URL_PLACEHOLDER", full_url)
            .replace("API_KEY_PLACEHOLDER", api_key_str)
            .replace("FILE_CODE_PLACEHOLDER", curl_file)
        )
        st.code(curl_code, language="bash")

    with tab_ts:
        ts_template = load_snippet("example.ts")
        if input_method == "Téléverser un fichier local":
            ts_file_code = """// Import Node.js filesystem module
import fs from 'fs';
const fileStream = fs.createReadStream('/chemin/vers/votre/fichier.pdf');
formData.append('file', fileStream as any);"""
        else:
            ts_file_code = f"formData.append('file_url', '{doc_url}');"

        if override:
            ts_template = ts_template.replace(
                "OVERRIDE_CODE_PLACEHOLDER",
                f"formData.append('override', JSON.stringify({override_json_str}));"
            )
        else:
            ts_template = ts_template.replace("OVERRIDE_CODE_PLACEHOLDER\n", "")

        if metadata:
            ts_template = ts_template.replace(
                "METADATA_CODE_PLACEHOLDER",
                f"formData.append('metadata', JSON.stringify({metadata_json_str}));"
            )
        else:
            ts_template = ts_template.replace("METADATA_CODE_PLACEHOLDER\n", "")

        ts_code = (
            ts_template.replace("URL_PLACEHOLDER", full_url)
            .replace("API_KEY_PLACEHOLDER", api_key_str)
            .replace("FILE_CODE_PLACEHOLDER", ts_file_code)
        )
        st.code(ts_code, language="typescript")

    with tab_java:
        java_template = load_snippet("example.java")
        if input_method == "Téléverser un fichier local":
            java_file_code = """File file = new File("/chemin/vers/votre/fichier.pdf");
        bodyBuilder.addFormDataPart("file", file.getName(),
            RequestBody.create(file, MediaType.parse("application/pdf")));"""
        else:
            java_file_code = f'bodyBuilder.addFormDataPart("file_url", "{doc_url}");'

        if override:
            java_template = java_template.replace(
                "OVERRIDE_CODE_PLACEHOLDER",
                f'bodyBuilder.addFormDataPart("override", "{override_escaped_java}");'
            )
        else:
            java_template = java_template.replace("        OVERRIDE_CODE_PLACEHOLDER\n", "")

        if metadata:
            java_template = java_template.replace(
                "METADATA_CODE_PLACEHOLDER",
                f'bodyBuilder.addFormDataPart("metadata", "{metadata_escaped_java}");'
            )
        else:
            java_template = java_template.replace("        METADATA_CODE_PLACEHOLDER\n", "")

        java_code = (
            java_template.replace("URL_PLACEHOLDER", full_url)
            .replace("API_KEY_PLACEHOLDER", api_key_str)
            .replace("FILE_CODE_PLACEHOLDER", java_file_code)
        )
        st.code(java_code, language="java")

    # Execution Action Button
    st.write("---")
    if st.button("Lancer le traitement", type="primary"):
        if input_method == "Téléverser un fichier local" and uploaded_file is None:
            st.warning("Veuillez sélectionner un fichier avant de lancer l'extraction.")
            return
        elif input_method == "URL du document" and not file_url:
            st.warning("Veuillez saisir une URL valide avant de lancer l'extraction.")
            return

        with st.spinner("Exécution du workflow..."):
            try:
                response = execute_workflow_v2(
                    workflow_id=selected_workflow["id"],
                    api_token=api_key,
                    file=uploaded_file,
                    file_url=file_url if input_method == "URL du document" else None,
                    override=override if override else None,
                    metadata=metadata if metadata else None,
                    sync=sync_mode,
                )
            except Exception as e:
                st.error(f"Erreur lors de l'exécution du workflow : {e}")
                return

        st.success("Requête envoyée avec succès !")

        if sync_mode:
            st.subheader("Résultat de l'exécution")
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

            st.info(f"ID de l'exécution : `{execution_id}`")

            with st.spinner("Attente du traitement de la réponse...", show_time=True):
                execution_details = wait_for_execution(execution_id, api_key)
                if execution_details is None:
                    st.error(f"Aucune exécution trouvée avec l'ID `{execution_id}`.")
                    return
                st.subheader("Résultat final")
                result_dict = (
                    execution_details.model_dump(mode="json") if execution_details else None
                )
                st.code(
                    json.dumps(result_dict, indent=2, ensure_ascii=False),
                    language="json",
                )


if __name__ == "__main__":
    main()
