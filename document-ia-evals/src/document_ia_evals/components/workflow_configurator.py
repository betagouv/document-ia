import streamlit as st
from typing import Any, Dict, Tuple
from document_ia_evals.utils.api import get_workflows


def render_workflow_configurator(
    api_key: str, key_suffix: str = ""
) -> Tuple[Dict[str, Any] | None, Dict[str, Any]]:
    """
    Renders the workflow configuration component.
    Allows selection of a workflow, displays its metadata, and renders the dynamic step overrides.

    Args:
        api_key (str): The API key for Document IA API
        key_suffix (str): Suffix to append to widget keys to avoid collisions

    Returns:
        Tuple of (selected_workflow_dict, override_dict)
    """
    # Retrieve and store workflows in session state
    if "workflows_data" not in st.session_state:
        try:
            with st.spinner("Fetching workflows..."):
                st.session_state["workflows_data"] = get_workflows(api_key)
        except Exception as e:
            st.error(f"Error fetching workflows: {e}")
            return None, {}

    # Extract workflows list
    workflows_response = st.session_state["workflows_data"]
    workflows = workflows_response.get("data", [])

    if not workflows:
        st.warning("No workflows available.")
        return None, {}

    # Dropdown with the list of available workflow names
    selected_workflow = st.selectbox(
        "Sélectionnez un workflow",
        options=workflows,
        format_func=lambda w: w.get("name", w.get("id")),
        key=f"workflow_selector{key_suffix}",
    )

    if not selected_workflow:
        return None, {}

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
                        f"{param_name} ({description})",
                        options=options,
                        index=index,
                        key=f"{step_action}_{param_name}{key_suffix}",
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
                            key=f"{step_action}_{param_name}{key_suffix}",
                        )
                    else:
                        value = st.number_input(
                            f"{param_name} - {description}",
                            value=(
                                float(default_val) if default_val is not None else 0.0
                            ),
                            step=0.1,
                            key=f"{step_action}_{param_name}{key_suffix}",
                        )
                elif param_schema.get("type") == "boolean":
                    value = st.checkbox(
                        f"{param_name} - {description}",
                        value=(bool(default_val) if default_val is not None else False),
                        key=f"{step_action}_{param_name}{key_suffix}",
                    )
                else:
                    value = st.text_input(
                        f"{param_name} - {description}",
                        value=(str(default_val) if default_val is not None else ""),
                        key=f"{step_action}_{param_name}{key_suffix}",
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

    return selected_workflow, override
