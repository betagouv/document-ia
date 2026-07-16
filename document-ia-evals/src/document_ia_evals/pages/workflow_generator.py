import streamlit as st

# Static mapping of workflow parameters to their anchor tags
ANCHOR_MAPPING = {
    "extract_barcode_data": {"barcode_type": "*barcode_type"},
    "extract_content_ocr": {"model": "*ocr_model"},
    "llm_classify_document": {
        "model": "*llm_model",
        "temperature": "*llm_temperature",
        "document_types": "*doc_types_array",
    },
    "llm_extract_data": {
        "model": "*llm_model",
        "temperature": "*llm_temperature",
        "document_type": "*doc_type_single",
    },
}

# Parameter defaults and options
PARAM_DESCRIPTIONS = {
    "barcode_type": "Type d'extraction code-barres (2ddoc)",
    "model": "Modèle d'inférence (OCR/LLM)",
    "temperature": "Température d'inférence",
    "document_types": "Types de classification",
    "document_type": "Type de document ciblé",
}


def main():
    title = "🛠️ Workflow Generator"
    st.set_page_config(page_title=title, page_icon="🛠️", layout="wide")
    st.title(title)
    st.caption(
        "Créez et configurez un nouveau workflow pour l'ajouter dans workflows.yaml"
    )

    # Initialize default workflow sequence in session state
    if "builder_steps" not in st.session_state:
        st.session_state["builder_steps"] = [
            {"action": "download_file", "params": {}},
            {"action": "preprocess_file", "params": {}},
            {
                "action": "extract_barcode_data",
                "params": {"barcode_type": "*barcode_type"},
            },
            {"action": "extract_content_ocr", "params": {"model": "*ocr_model"}},
            {
                "action": "llm_classify_document",
                "params": {
                    "model": "*llm_model",
                    "temperature": "*llm_temperature",
                    "document_types": "*doc_types_array",
                },
            },
            {
                "action": "llm_extract_data",
                "params": {"model": "*llm_model", "temperature": "*llm_temperature"},
            },
            {"action": "save_workflow_result", "params": {}},
        ]

    # Visual Columns
    col_meta, col_steps = st.columns([1, 1])

    with col_meta:
        st.subheader("1. Métadonnées du Workflow")

        wf_id = st.text_input(
            "ID du Workflow (ex: cni-extraction-v2)", value="custom-workflow-v2"
        )
        wf_name = st.text_input(
            "Nom du Workflow", value="CNI Extraction and validation workflow"
        )
        wf_desc = st.text_area(
            "Description", value="Workflow personnalisé pour l'extraction de CNI."
        )
        wf_version = st.text_input("Version", value="2.0.0")

        col_wf_enabled, col_wf_timeout = st.columns(2)
        with col_wf_enabled:
            wf_enabled = st.checkbox("Activé par défaut (enabled)", value=True)
        with col_wf_timeout:
            wf_timeout = st.number_input("Timeout (minutes)", value=5, min_value=1)

        wf_max_size = st.number_input(
            "Taille max autorisée (Mo)", value=25, min_value=1
        )

        wf_types = st.multiselect(
            "Types de fichiers acceptés",
            options=["application/pdf", "image/jpeg", "image/png", "image/tiff"],
            default=["application/pdf", "image/jpeg", "image/png"],
        )

    with col_steps:
        st.subheader("2. Séquence des Étapes")

        # Step management helpers
        def move_up(idx):
            if idx > 0:
                steps = st.session_state["builder_steps"]
                steps[idx], steps[idx - 1] = steps[idx - 1], steps[idx]
                st.session_state["builder_steps"] = steps
                st.rerun()

        def move_down(idx):
            steps = st.session_state["builder_steps"]
            if idx < len(steps) - 1:
                steps[idx], steps[idx + 1] = steps[idx + 1], steps[idx]
                st.session_state["builder_steps"] = steps
                st.rerun()

        def remove_step(idx):
            steps = st.session_state["builder_steps"]
            steps.pop(idx)
            st.session_state["builder_steps"] = steps
            st.rerun()

        # Render list of current steps
        steps = st.session_state["builder_steps"]
        updated_steps = []

        for idx, step in enumerate(steps):
            action = step["action"]

            with st.container(border=True):
                c_info, c_params, c_actions = st.columns([2, 3, 1.5])

                with c_info:
                    st.markdown(f"**#{idx + 1}** `{action}`")

                # Check config parameters for this step action
                step_params = {}
                possible_params = ANCHOR_MAPPING.get(action, {})

                with c_params:
                    if possible_params:
                        st.caption("Paramètres :")
                        for p_name, p_anchor in possible_params.items():
                            desc = PARAM_DESCRIPTIONS.get(p_name, p_name)
                            # Set default checked state if parameter was already in the step params
                            default_checked = p_name in step.get("params", {})

                            checked = st.checkbox(
                                f"{p_name} ({p_anchor})",
                                value=default_checked,
                                key=f"step_{idx}_{action}_{p_name}",
                                help=desc,
                            )
                            if checked:
                                step_params[p_name] = p_anchor
                    else:
                        st.caption("Aucun paramètre.")

                with c_actions:
                    c_up, c_down, c_del = st.columns(3)
                    with c_up:
                        if st.button("⬆️", key=f"up_{idx}", help="Monter"):
                            move_up(idx)
                    with c_down:
                        if st.button("⬇️", key=f"down_{idx}", help="Descendre"):
                            move_down(idx)
                    with c_del:
                        if st.button("❌", key=f"del_{idx}", help="Supprimer"):
                            remove_step(idx)

                # Store updated step params
                updated_steps.append({"action": action, "params": step_params})

        # Update session state with the selected checkbox values
        st.session_state["builder_steps"] = updated_steps

        st.write("---")
        st.markdown("**Ajouter une nouvelle étape**")
        col_new_select, col_new_add = st.columns([3, 1])

        with col_new_select:
            all_known_actions = [
                "download_file",
                "preprocess_file",
                "extract_barcode_data",
                "extract_content_ocr",
                "llm_classify_document",
                "llm_extract_data",
                "save_workflow_result",
            ]
            new_action_choice = st.selectbox(
                "Action",
                options=all_known_actions + ["Autre (Saisie libre...)"],
                index=0,
            )

            if new_action_choice == "Autre (Saisie libre...)":
                new_action = st.text_input("Nom de l'action personnalisée :")
            else:
                new_action = new_action_choice

        with col_new_add:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("➕ Ajouter", use_container_width=True):
                if new_action:
                    # Resolve default params if known action
                    default_params = {}
                    if new_action in ANCHOR_MAPPING:
                        # Add all params as checked by default, except document_type in extraction (which is conditional)
                        for k, v in ANCHOR_MAPPING[new_action].items():
                            if k != "document_type":
                                default_params[k] = v

                    st.session_state["builder_steps"].append(
                        {"action": new_action, "params": default_params}
                    )
                    st.rerun()

    # Generate YAML block
    st.write("---")
    st.subheader("📋 Bloc YAML Généré")
    st.markdown("Copiez et collez ce bloc à la fin du fichier `workflows.yaml` :")

    yaml_lines = []
    yaml_lines.append(f"- id: {wf_id}")
    yaml_lines.append(f"  name: {wf_name}")
    yaml_lines.append(f"  description: {wf_desc}")
    yaml_lines.append(f"  version: {wf_version}")
    yaml_lines.append(f"  enabled: {str(wf_enabled).lower()}")
    yaml_lines.append("  supported_file_types:")
    for ft in wf_types:
        yaml_lines.append(f"    - {ft}")
    yaml_lines.append(f"  max_file_size_mb: {wf_max_size}")
    yaml_lines.append(f"  processing_timeout_minutes: {wf_timeout}")
    yaml_lines.append("  steps:")

    for step in st.session_state["builder_steps"]:
        yaml_lines.append(f"    - action: {step['action']}")
        if step.get("params"):
            yaml_lines.append("      params:")
            for p_name, p_anchor in step["params"].items():
                yaml_lines.append(f"        {p_name}: {p_anchor}")

    generated_yaml = "\n".join(yaml_lines)
    st.code(generated_yaml, language="yaml")


if __name__ == "__main__":
    main()
