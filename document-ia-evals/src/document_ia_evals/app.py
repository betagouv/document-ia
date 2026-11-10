"""Main Streamlit application entry point."""

import streamlit as st

from document_ia_evals.components.auth_ui import (
    render_access_denied_screen,
    render_login_screen,
    render_sidebar_user_profile,
)
from document_ia_evals.services.auth_service import verify_user_access
from document_ia_evals.utils.auth_secrets import generate_secrets_toml
from document_ia_evals.utils.config import config

# Ensure directories and secrets configuration exist
config.ensure_directories()
generate_secrets_toml()

# Page configuration
st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon=config.PAGE_ICON,
    layout=config.LAYOUT,  # pyright: ignore [reportArgumentType]
    initial_sidebar_state="expanded",
)


def main():
    """Main application function."""
    st.logo(
        "src/document_ia_evals/assets/logo.svg",
        link="https://beta.gouv.fr/startups/document-ia",
        size="large",
    )

    # 1. Local development offline bypass
    if config.AUTH_BYPASS_LOCAL:
        st.session_state["current_user_email"] = "nicolas.sagon@beta.gouv.fr"
        st.session_state["current_user_role"] = "admin"
        st.session_state["current_user_id"] = "bypass-local-admin"

    # 2. Check Streamlit native OIDC login status safely
    is_logged_in = config.AUTH_BYPASS_LOCAL or bool(
        getattr(st.user, "is_logged_in", False)
    )

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

    # 3. Retrieve user email from ProConnect claims (or local bypass)
    raw_email = (
        st.session_state.get("current_user_email")
        if config.AUTH_BYPASS_LOCAL
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

    # 4. Verify authorization against database
    user_role = "admin"
    if not config.AUTH_BYPASS_LOCAL:
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

    # 5. User is authenticated and authorized -> render sidebar profile and navigation
    render_sidebar_user_profile()

    pages = {
        "Home": [
            st.Page("pages/home.py", title="🏠 Home"),
        ],
        "API Playground": [
            st.Page(
                "pages/run_api_workflow.py", title="📄 Execute Workflow (Deprecated)"
            ),
            st.Page("pages/run_api_workflow_v2.py", title="📄 Execute Workflow V2"),
            st.Page(
                "pages/retrieve_api_execution.py", title="🔍 Retrieve Past Execution"
            ),
        ],
        "Pipeline Evaluation": [
            st.Page(
                "pages/create_dataset.py", title="📝 Create Ground Truth (Deprecated)"
            ),
            st.Page("pages/create_dataset_v2.py", title="📝 Create Ground Truth V2"),
            st.Page(
                "pages/create_predictions.py",
                title="🔄 Create New Predictions (Deprecated)",
            ),
            st.Page(
                "pages/create_predictions_v2.py", title="🔄 Create New Predictions V2"
            ),
            st.Page(
                "pages/evaluate_metrics.py",
                title="🎯 Evaluate Predictions Metrics (Deprecated)",
            ),
            st.Page(
                "pages/evaluate_metrics_v2.py",
                title="🎯 Evaluate Predictions Metrics V2",
            ),
            st.Page(
                "pages/review_prediction_errors.py",
                title="🔎 Review prediction errors",
            ),
            st.Page("pages/list_experiments.py", title="📚 List Previous Evaluations"),
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
    }

    # Administration page is ONLY registered for users with admin role
    if user_role == "admin":
        pages["Administration"] = [
            st.Page("pages/administration.py", title="⚙️ Administration"),
        ]

    pg = st.navigation(pages, position="sidebar")
    pg.run()


if __name__ == "__main__":
    main()
