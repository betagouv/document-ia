"""Main Streamlit application entry point."""

import streamlit as st

from document_ia_evals.components.auth_ui import (
    render_access_denied_screen,
    render_login_screen,
    render_sidebar_user_profile,
)
from document_ia_evals.services.auth_service import (
    is_local_bypass_allowed,
    verify_user_access,
)
from document_ia_evals.utils.auth_secrets import (
    generate_secrets_toml,
    patch_streamlit_oidc_prompt,
)
from document_ia_evals.utils.config import config


@st.cache_resource
def _bootstrap_auth_once() -> None:
    """Bootstrap directories and OIDC secrets configuration once per process."""
    patch_streamlit_oidc_prompt()
    config.ensure_directories()
    generate_secrets_toml()


_bootstrap_auth_once()

# Page configuration
st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon=config.PAGE_ICON,
    layout=config.LAYOUT,  # pyright: ignore [reportArgumentType]
    initial_sidebar_state="expanded",
)


def main():
    """Main application function."""
    # S4 / Issue #155: Purge active et systématique de tout reliquat historique d'env_key et env_url dans l'URL
    st.query_params.pop("env_key", None)
    st.query_params.pop("env_url", None)

    st.logo(
        "src/document_ia_evals/assets/logo.svg",
        link="https://beta.gouv.fr/startups/document-ia",
        size="large",
    )

    # 1. Local development offline bypass (with strict host/environment verification)
    bypass_allowed = is_local_bypass_allowed()
    if bypass_allowed:
        st.session_state["current_user_email"] = "nicolas.sagon@beta.gouv.fr"
        st.session_state["current_user_role"] = "admin"
        st.session_state["current_user_id"] = "bypass-local-admin"

    # 2. Check Streamlit native OIDC login status safely
    is_logged_in = bypass_allowed or bool(getattr(st.user, "is_logged_in", False))

    if not is_logged_in:
        # Hide all navigation and sidebar menu, display ONLY the login page
        login_page = st.Page(
            render_login_screen,
            title="Connexion",
            icon="🔐",
            default=True,
        )
        pg = st.navigation([login_page], position="hidden")
        pg.run()
        return

    # 3. Retrieve user email from verified ProConnect claims (or local bypass)
    raw_email = (
        st.session_state.get("current_user_email")
        if bypass_allowed
        else (
            getattr(st.user, "email", None)
            or (st.user.get("email") if hasattr(st.user, "get") else None)
        )
    )
    user_email = str(raw_email).strip().lower() if raw_email else None

    if not user_email:
        denied_page = st.Page(
            lambda: render_access_denied_screen(
                email="Inconnu",
                reason="Aucune adresse email n'a été transmise par ProConnect.",
            ),
            title="Accès non autorisé",
            icon="⛔",
            default=True,
        )
        pg = st.navigation([denied_page], position="hidden")
        pg.run()
        return

    # 4. Verify authorization against database (read-only guard)
    user_role = "admin"
    if not bypass_allowed:
        is_allowed, user, reason = verify_user_access(user_email)
        if not is_allowed or user is None:
            denied_page = st.Page(
                lambda: render_access_denied_screen(
                    email=user_email,
                    reason=reason,
                ),
                title="Accès non autorisé",
                icon="⛔",
                default=True,
            )
            pg = st.navigation([denied_page], position="hidden")
            pg.run()
            return

        st.session_state["current_user_email"] = user.email
        st.session_state["current_user_role"] = user.role
        st.session_state["current_user_id"] = str(user.id)
        user_role = user.role

    # 5. User is authenticated and authorized -> render sidebar profile at top
    render_sidebar_user_profile()

    # 6. Role-Based Access Control: Admins see all pages, users see only API Playground
    if user_role == "admin":
        pages = {
            "Home": [
                st.Page("pages/home.py", title="🏠 Home", default=True),
            ],
            "API Playground": [
                st.Page("pages/run_api_workflow_v2.py", title="📄 Execute Workflow V2"),
                st.Page(
                    "pages/retrieve_api_execution.py",
                    title="🔍 Retrieve Past Execution",
                ),
                st.Page(
                    "pages/run_api_workflow.py",
                    title="📄 Execute Workflow (Deprecated)",
                ),
            ],
            "Pipeline Evaluation": [
                st.Page(
                    "pages/create_dataset_v2.py", title="📝 Create Ground Truth V2"
                ),
                st.Page(
                    "pages/create_dataset.py",
                    title="📝 Create Ground Truth (Deprecated)",
                ),
                st.Page(
                    "pages/create_predictions_v2.py",
                    title="🔄 Create New Predictions V2",
                ),
                st.Page(
                    "pages/create_predictions.py",
                    title="🔄 Create New Predictions (Deprecated)",
                ),
                st.Page(
                    "pages/evaluate_metrics_v2.py",
                    title="🎯 Evaluate Predictions Metrics V2",
                ),
                st.Page(
                    "pages/evaluate_metrics.py",
                    title="🎯 Evaluate Predictions Metrics (Deprecated)",
                ),
                st.Page(
                    "pages/review_prediction_errors.py",
                    title="🔎 Review prediction errors",
                ),
                st.Page(
                    "pages/list_experiments.py",
                    title="📚 List Previous Evaluations",
                ),
            ],
            "Prompt Playground": [
                st.Page("pages/prompt_playground.py", title="⚙️ Prompt Playground"),
            ],
            "Data": [
                st.Page("pages/export_dataset.py", title="📤 Export Dataset"),
            ],
            "Tool": [
                st.Page("pages/workflow_generator.py", title="🛠️ Workflow Generator"),
            ],
            "Administration": [
                st.Page("pages/admin_users.py", title="👥 Accès Console"),
                st.Page("pages/admin_api_keys.py", title="🔑 Organisation & Clés API"),
            ],
        }
    else:
        # Non-admin users are restricted exclusively to the API Playground
        pages = {
            "API Playground": [
                st.Page(
                    "pages/run_api_workflow_v2.py",
                    title="📄 Execute Workflow V2",
                    default=True,
                ),
                st.Page(
                    "pages/retrieve_api_execution.py",
                    title="🔍 Retrieve Past Execution",
                ),
                st.Page(
                    "pages/run_api_workflow.py",
                    title="📄 Execute Workflow (Deprecated)",
                ),
            ],
        }

    pg = st.navigation(pages, position="sidebar")
    pg.run()


if __name__ == "__main__":
    main()
