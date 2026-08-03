"""Component for environment selection and API key input in Streamlit apps."""

import streamlit as st

DEFAULT_ENVIRONMENTS = {
    "🟡 Staging": "https://api.staging.document-ia.beta.gouv.fr",
    "🟢 Sandbox": "https://api.sandbox.document-ia.beta.gouv.fr",
    "🔴 Production": "https://api.document-ia.beta.gouv.fr",
    "⚙️ URL personnalisée": "custom",
}


def render_sidebar_auth(
    allow_custom_url: bool = True,
    default_env: str = "🟢 Sandbox",
    key_prefix: str = "global_",
) -> tuple[str, str]:
    """Renders the environment selector and API Key input in the sidebar.

    Returns:
        tuple[str, str]: (base_url, api_key)
    """
    st.sidebar.title("🔐 Connexion API")

    env_options = list(DEFAULT_ENVIRONMENTS.keys())
    if not allow_custom_url:
        env_options = [k for k in env_options if k != "⚙️ URL personnalisée"]

    selected_env_label = st.sidebar.selectbox(
        "Environnement Target",
        options=env_options,
        index=env_options.index(default_env) if default_env in env_options else 0,
        key=f"{key_prefix}env_selector",
    )

    if DEFAULT_ENVIRONMENTS[selected_env_label] == "custom":
        base_url = st.sidebar.text_input(
            "URL de l'API",
            value=st.session_state.get(f"{key_prefix}custom_url", "http://localhost:8000"),
            placeholder="https://api.votre-domaine.fr",
            key=f"{key_prefix}custom_url_input",
        )
    else:
        base_url = DEFAULT_ENVIRONMENTS[selected_env_label]

    api_key = st.sidebar.text_input(
        "Clé API Document IA",
        type="password",
        value=st.session_state.get(f"{key_prefix}api_key", ""),
        placeholder="votre-cle-api",
        key=f"{key_prefix}api_key_input",
        help="Entrez votre clé API personnelle",
    )

    base_url = base_url.rstrip("/") if base_url else ""

    # Persist in session state
    st.session_state["api_base_url"] = base_url
    st.session_state["api_key"] = api_key

    st.sidebar.markdown("---")
    if base_url:
        st.sidebar.caption(f"📍 **URL active :** `{base_url}`")

    return base_url, api_key
