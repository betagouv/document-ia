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
        st.error("⛔ Accès non autorisé")
        st.markdown(f"**Identité ProConnect** : `{email}`")
        st.warning(reason)

        st.markdown(
            "Votre compte n'a pas été enrôlé dans la liste des utilisateurs autorisés de Document IA. "
            "Veuillez vous rapprocher d'un administrateur du projet pour obtenir les accès."
        )

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("Se déconnecter", type="secondary", use_container_width=True):
            record_logout(email)
            st.logout()


def render_sidebar_user_profile() -> None:
    """Render current user profile badge and logout button in Streamlit sidebar."""
    email = st.session_state.get("current_user_email", "Utilisateur")
    role = st.session_state.get("current_user_role", "user")

    role_label = "👑 Administrateur" if role == "admin" else "👤 Évaluateur"

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Connecté :** `{email}`")
    st.sidebar.markdown(f"**Rôle :** {role_label}")

    if st.sidebar.button(
        "Se déconnecter", key="sidebar_logout_btn", use_container_width=True
    ):
        record_logout(email)
        st.session_state.clear()
        st.logout()
