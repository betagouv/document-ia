"""UI components for ProConnect authentication and user profile display."""

import streamlit as st

from document_ia_evals.services.auth_service import record_logout


def render_login_screen() -> None:
    """Render the official ProConnect login screen."""
    _, col2, _ = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 Document IA — Évaluation")
        st.markdown(
            "Bienvenue sur la console d'évaluation et de benchmark de **Document IA**."
        )

        st.info(
            "L'accès à cette plateforme est restreint aux agents habilités de l'État via le service **ProConnect**."
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # Official ProConnect login button
        login_clicked = st.button(
            "🇫🇷 S'identifier avec ProConnect",
            type="primary",
            use_container_width=True,
            key="proconnect_login_btn",
        )

        if login_clicked:
            st.login("proconnect")

        st.markdown("<br><br>", unsafe_allow_html=True)
        st.caption(
            "ProConnect est le service d'authentification fédérée de l'État (DINUM). "
            "En cas de difficulté d'accès, contactez l'équipe Document IA."
        )


def render_access_denied_screen(email: str, reason: str) -> None:
    """Render the access denied screen when user is authenticated via ProConnect but not authorized."""
    _, col2, _ = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.error("⛔ 401 — Accès non autorisé")
        st.markdown(f"**Identité ProConnect :** `{email}`")
        st.warning(reason)

        st.markdown(
            "Votre compte est authentifié auprès de ProConnect mais n'est pas autorisé "
            "à accéder à la console Document IA. Rapprochez-vous d'un administrateur du projet."
        )

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button(
            "🚪 Se déconnecter de ProConnect",
            type="primary",
            use_container_width=True,
            key="btn_denied_logout",
        ):
            record_logout(email)
            st.session_state.clear()
            st.logout()


def enforce_page_auth(required_role: str | None = None) -> None:
    """Defense-in-depth security guard for individual page execution."""
    from document_ia_evals.utils.config import config

    if config.AUTH_BYPASS_LOCAL:
        return

    is_logged_in = bool(getattr(st.user, "is_logged_in", False))
    if not is_logged_in:
        st.error("🔒 Authentification requise. Veuillez vous connecter.")
        if st.button("Se connecter avec ProConnect", type="primary"):
            st.login("proconnect")
        st.stop()

    email = st.session_state.get("current_user_email")
    role = st.session_state.get("current_user_role")

    if not email:
        st.error("⛔ Session invalide. Veuillez vous reconnecter.")
        if st.button("Se déconnecter", type="secondary"):
            st.session_state.clear()
            st.logout()
        st.stop()

    if required_role == "admin" and role != "admin":
        st.error("⛔ Accès refusé : cette page est réservée aux administrateurs.")
        st.stop()


def render_sidebar_user_profile() -> None:
    """Render current user profile badge and logout button at the top of Streamlit sidebar."""
    email = st.session_state.get("current_user_email", "Utilisateur")
    role = st.session_state.get("current_user_role", "user")
    name = getattr(st.user, "name", None) or (
        st.user.get("name") if hasattr(st.user, "get") else None
    )

    role_label = "👑 Administrateur" if role == "admin" else "👤 Évaluateur"

    # CSS to position stSidebarUserContent (which hosts this profile) at the very top of the sidebar
    st.markdown(
        """
        <style>
        /* Force sidebar content to flex and reorder user profile above navigation */
        [data-testid="stSidebarContent"] {
            display: flex !important;
            flex-direction: column !important;
        }
        [data-testid="stSidebarHeader"] {
            order: 0 !important;
        }
        [data-testid="stSidebarUserContent"] {
            order: 1 !important;
            padding-top: 0.25rem !important;
            padding-bottom: 0.5rem !important;
        }
        [data-testid="stSidebarNav"] {
            order: 2 !important;
        }
        .user-profile-card {
            background-color: rgba(128, 128, 128, 0.08);
            border-left: 4px solid #000091;
            border-radius: 6px;
            padding: 10px 12px;
            margin-bottom: 8px;
        }
        .user-profile-title {
            font-weight: 600;
            font-size: 0.95rem;
            color: inherit;
        }
        .user-profile-meta {
            font-size: 0.8rem;
            color: #666;
            margin-top: 2px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    display_name = name if name else email
    display_sub = f"{email} • {role_label}" if name else role_label

    st.sidebar.markdown(
        f"""
        <div class="user-profile-card">
            <div class="user-profile-title">👤 {display_name}</div>
            <div class="user-profile-meta">{display_sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.sidebar.button(
        "🚪 Se déconnecter",
        key="sidebar_logout_btn",
        use_container_width=True,
    ):
        record_logout(email)
        st.session_state.clear()
        st.logout()

    st.sidebar.markdown("---")
