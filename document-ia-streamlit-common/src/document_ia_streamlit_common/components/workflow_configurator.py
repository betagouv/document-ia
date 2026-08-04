"""Workflow configurator component shared across Streamlit apps."""

from typing import Any, Dict, Tuple
import streamlit as st
from document_ia_streamlit_common.api import get_workflows


def render_workflow_configurator(
    base_url: str,
    api_key: str,
    key_suffix: str = "",
    default_workflow_id: str | None = None,
    default_document_type: str | None = None,
) -> Tuple[Dict[str, Any] | None, Dict[str, Any]]:
    """Renders the workflow configuration component.

    Allows selection of a workflow, displays its metadata, and renders dynamic step overrides.

    Args:
        base_url (str): Target API Base URL
        api_key (str): The API key for Document IA API
        key_suffix (str): Suffix to append to widget keys to avoid collisions
        default_workflow_id (str): Optional workflow ID to pre-select
        default_document_type (str): Optional document type to pre-select

    Returns:
        Tuple of (selected_workflow_dict, override_dict)
    """
    if not base_url or not api_key:
        st.warning("⚠️ Veuillez renseigner l'URL de l'environnement et votre clé API dans la barre latérale.")
        return None, {}

    # Clear workflows_data cache if base_url or api_key changed
    cache_key = f"workflows_data_{base_url}_{api_key[:8] if len(api_key)>=8 else api_key}"
    if st.session_state.get("current_workflow_cache_key") != cache_key:
        st.session_state.pop("workflows_data", None)
        st.session_state["current_workflow_cache_key"] = cache_key

    # Retrieve and store workflows in session state
    if "workflows_data" not in st.session_state:
        try:
            with st.spinner("Chargement des workflows..."):
                st.session_state["workflows_data"] = get_workflows(base_url, api_key)
        except Exception as e:
            st.error(f"Erreur lors de la récupération des workflows : {e}")
            return None, {}

    workflows_response = st.session_state["workflows_data"]
    workflows = workflows_response.get("data", [])

    if not workflows:
        st.warning("Aucun workflow disponible pour cet environnement.")
        return None, {}

    widget_key = f"workflow_selector{key_suffix}"
    tracker_key = f"last_default_workflow_id{key_suffix}"

    matching_workflow = None
    if default_workflow_id:
        for w in workflows:
            if w.get("id") == default_workflow_id:
                matching_workflow = w
                break

    if default_workflow_id != st.session_state.get(tracker_key):
        st.session_state[tracker_key] = default_workflow_id
        if matching_workflow:
            st.session_state[widget_key] = matching_workflow

    tracker_doc_key = f"last_default_doc_type{key_suffix}"
    if default_document_type != st.session_state.get(tracker_doc_key):
        st.session_state[tracker_doc_key] = default_document_type
        selected_workflow_state = st.session_state.get(
            widget_key, matching_workflow or (workflows[0] if workflows else None)
        )
        if selected_workflow_state:
            for step in selected_workflow_state.get("steps", []):
                step_action = step.get("action")
                params_schema = step.get("params", {})
                for param_name, param_schema in params_schema.items():
                    if (
                        param_name in ["document_type", "document-type"]
                        and default_document_type
                    ):
                        param_key = f"{step_action}_{param_name}{key_suffix}"
                        if "enum" in param_schema:
                            if default_document_type in param_schema["enum"]:
                                st.session_state[param_key] = default_document_type
                        else:
                            st.session_state[param_key] = default_document_type

    selected_workflow = st.selectbox(
        "Sélectionnez un workflow",
        options=workflows,
        format_func=lambda w: f"{w.get('name', w.get('id'))} (v{w.get('version', '1')})",
        key=widget_key,
    )

    if not selected_workflow:
        return None, {}

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

                if "oneOf" in param_schema:
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
                            key=f"{step_action}_{param_name}_mode{key_suffix}",
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
                                key=f"{step_action}_{param_name}_multiselect{key_suffix}",
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
                        f"{param_name} ({description})" if description else param_name,
                        options=options,
                        index=index,
                        key=f"{step_action}_{param_name}{key_suffix}",
                    )
                elif param_schema.get("type") == "float":
                    if "temperature" in param_name:
                        value = st.slider(
                            f"{param_name} - {description}" if description else param_name,
                            min_value=0.0,
                            max_value=1.0,
                            value=(
                                float(default_val) if default_val is not None else 0.0
                            ),
                            step=0.1,
                            key=f"{step_action}_{param_name}{key_suffix}",
                        )
                    else:
                        value = st.number_input(
                            f"{param_name} - {description}" if description else param_name,
                            value=(
                                float(default_val) if default_val is not None else 0.0
                            ),
                            step=0.1,
                            key=f"{step_action}_{param_name}{key_suffix}",
                        )
                elif param_schema.get("type") == "boolean":
                    value = st.checkbox(
                        f"{param_name} - {description}" if description else param_name,
                        value=(bool(default_val) if default_val is not None else False),
                        key=f"{step_action}_{param_name}{key_suffix}",
                    )
                else:
                    value = st.text_input(
                        f"{param_name} - {description}" if description else param_name,
                        value=(str(default_val) if default_val is not None else ""),
                        key=f"{step_action}_{param_name}{key_suffix}",
                    )

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

    return selected_workflow, override
