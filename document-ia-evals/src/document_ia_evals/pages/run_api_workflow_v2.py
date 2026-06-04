import json
import streamlit as st

from document_ia_evals.utils.api import (
    execute_workflow_v2,
    get_workflows,
    wait_for_execution,
)
from document_ia_evals.utils.config import config


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

    # Retrieve and store workflows in session state
    if "workflows_data" not in st.session_state:
        try:
            with st.spinner("Fetching workflows..."):
                st.session_state["workflows_data"] = get_workflows(api_key)
        except Exception as e:
            st.error(f"Error fetching workflows: {e}")
            return

    # Extract workflows list
    workflows_response = st.session_state["workflows_data"]
    workflows = workflows_response.get("data", [])

    if not workflows:
        st.warning("No workflows available.")
        return

    # Dropdown with the list of available workflow names
    selected_workflow = st.selectbox(
        "Sélectionnez un workflow",
        options=workflows,
        format_func=lambda w: w.get("name", w.get("id")),
    )

    if not selected_workflow:
        return

    # Display workflow metadata
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Version :** {selected_workflow.get('version', 'N/A')}")
        st.markdown(
            f"**Description :** {selected_workflow.get('description', 'Aucune description.')}"
        )
    with col2:
        st.markdown(
            f"**Types supportés :** `{', '.join(selected_workflow.get('supported_file_types', []))}`"
        )
        st.markdown(
            f"**Taille max :** `{selected_workflow.get('max_file_size_mb', 25)} Mo`"
        )

    st.write("---")
    st.subheader("🛠️ Configuration des étapes du workflow")

    override = {}

    for step in selected_workflow.get("steps", []):
        step_action = step.get("action")
        params_schema = step.get("params", {})

        if not params_schema:
            st.info(f"⏭️ **Étape : {step_action}** (Aucun paramètre configurable)")
            continue

        with st.expander(f"⚙️ **Étape : {step_action}**", expanded=True):
            step_overrides_list = []

            for param_name, param_schema in params_schema.items():
                value = None
                description = param_schema.get("description", "")
                default_val = param_schema.get("default")

                # Check for oneOf
                if "oneOf" in param_schema:
                    # Detect if it's the "all" string vs array of enums
                    string_all_option = None
                    array_option = None
                    for opt in param_schema["oneOf"]:
                        if opt.get("type") == "string" and opt.get("enum") == ["all"]:
                            string_all_option = opt
                        elif opt.get("type") == "array" and "items" in opt:
                            array_option = opt

                    if string_all_option and array_option:
                        mode = st.radio(
                            f"{param_name} - Mode",
                            options=["Tous", "Sélectionner des types spécifiques"],
                            index=0 if default_val == "all" else 1,
                            key=f"{step_action}_{param_name}_mode",
                            help=description,
                        )
                        if mode == "Tous":
                            value = "all"
                        else:
                            items_schema = array_option["items"]
                            options = items_schema.get("enum", [])
                            default_items = (
                                default_val if isinstance(default_val, list) else []
                            )
                            value = st.multiselect(
                                f"Types de documents pour {param_name}",
                                options=options,
                                default=default_items,
                                key=f"{step_action}_{param_name}_multiselect",
                                help=description,
                            )
                elif "enum" in param_schema:
                    options = param_schema["enum"]
                    try:
                        index = (
                            options.index(default_val) if default_val in options else 0
                        )
                    except ValueError:
                        index = 0
                    value = st.selectbox(
                        f"{param_name} ({description})",
                        options=options,
                        index=index,
                        key=f"{step_action}_{param_name}",
                    )
                elif param_schema.get("type") == "float":
                    if "temperature" in param_name:
                        value = st.slider(
                            f"{param_name} - {description}",
                            min_value=0.0,
                            max_value=1.0,
                            value=(
                                float(default_val) if default_val is not None else 0.0
                            ),
                            step=0.1,
                            key=f"{step_action}_{param_name}",
                        )
                    else:
                        value = st.number_input(
                            f"{param_name} - {description}",
                            value=(
                                float(default_val) if default_val is not None else 0.0
                            ),
                            step=0.1,
                            key=f"{step_action}_{param_name}",
                        )
                elif param_schema.get("type") == "boolean":
                    value = st.checkbox(
                        f"{param_name} - {description}",
                        value=(bool(default_val) if default_val is not None else False),
                        key=f"{step_action}_{param_name}",
                    )
                else:
                    value = st.text_input(
                        f"{param_name} - {description}",
                        value=(str(default_val) if default_val is not None else ""),
                        key=f"{step_action}_{param_name}",
                    )

                # Compare value with default to determine if we should send it in override
                is_modified = False
                if "default" in param_schema:
                    if value != param_schema["default"]:
                        is_modified = True
                else:
                    is_modified = True

                if is_modified:
                    step_overrides_list.append({"param": param_name, "value": value})

            if step_overrides_list:
                override[step_action] = step_overrides_list

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
        curl_file = (
            '-F "file=@/chemin/vers/votre/fichier.pdf"'
            if input_method == "Téléverser un fichier local"
            else f'-F "file_url={doc_url}"'
        )
        curl_override = f"  -F 'override={override_json_str}' \\\n" if override else ""
        curl_metadata = f"  -F 'metadata={metadata_json_str}' \\\n" if metadata else ""

        curl_code = f"""curl -X POST "{full_url}" \\
  -H "X-API-KEY: {api_key_str}" \\
  {curl_file} \\
{curl_override}{curl_metadata}  -H "Accept: application/json\""""
        st.code(curl_code, language="bash")

    with tab_ts:
        if input_method == "Téléverser un fichier local":
            ts_file_code = """// Import Node.js filesystem module
import fs from 'fs';
const fileStream = fs.createReadStream('/chemin/vers/votre/fichier.pdf');
formData.append('file', fileStream as any);"""
        else:
            ts_file_code = f"formData.append('file_url', '{doc_url}');"

        ts_override_code = (
            f"formData.append('override', JSON.stringify({override_json_str}));"
            if override
            else ""
        )
        ts_metadata_code = (
            f"formData.append('metadata', JSON.stringify({metadata_json_str}));"
            if metadata
            else ""
        )

        ts_code = f"""import fetch from 'node-fetch'; // si < Node.js 18

const url = "{full_url}";
const apiKey = "{api_key_str}";

const formData = new FormData();
{ts_file_code}
{ts_override_code}
{ts_metadata_code}

const response = await fetch(url, {{
  method: 'POST',
  headers: {{
    'X-API-KEY': apiKey,
  }},
  body: formData
}});

const data = await response.json();
console.log(data);"""
        st.code(ts_code, language="typescript")

    with tab_java:
        if input_method == "Téléverser un fichier local":
            java_file_code = """        File file = new File("/chemin/vers/votre/fichier.pdf");
        bodyBuilder.addFormDataPart("file", file.getName(),
            RequestBody.create(file, MediaType.parse("application/pdf")));"""
        else:
            java_file_code = (
                f'        bodyBuilder.addFormDataPart("file_url", "{doc_url}");'
            )

        java_override_code = (
            f'        bodyBuilder.addFormDataPart("override", "{override_escaped_java}");'
            if override
            else ""
        )
        java_metadata_code = (
            f'        bodyBuilder.addFormDataPart("metadata", "{metadata_escaped_java}");'
            if metadata
            else ""
        )

        java_code = f"""import okhttp3.*;
import java.io.File;
import java.io.IOException;

public class DocumentIaClient {{
    public static void main(String[] args) throws IOException {{
        OkHttpClient client = new OkHttpClient().newBuilder().build();

        MultipartBody.Builder bodyBuilder = new MultipartBody.Builder()
            .setType(MultipartBody.FORM);

{java_file_code}
{java_override_code}
{java_metadata_code}

        RequestBody body = bodyBuilder.build();

        Request request = new Request.Builder()
            .url("{full_url}")
            .post(body)
            .addHeader("X-API-KEY", "{api_key_str}")
            .addHeader("Accept", "application/json")
            .build();

        try (Response response = client.newCall(request).execute()) {{
            if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);
            System.out.println(response.body().string());
        }}
    }}
}}"""
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
                    execution_details.model_dump() if execution_details else None
                )
                st.code(
                    json.dumps(result_dict, indent=2, ensure_ascii=False),
                    language="json",
                )


if __name__ == "__main__":
    main()
