"""Administration page for Console Access and RBAC permissions."""

import pandas as pd
import streamlit as st

from document_ia_evals.components.auth_ui import enforce_page_auth
from document_ia_evals.database.models import UserRole
from document_ia_evals.services.auth_service import (
    add_evals_user,
    list_evals_users,
    list_recent_access_logs,
    update_evals_user,
)
from document_ia_evals.utils.config import config

st.set_page_config(
    page_title=f"Accès Console | {config.APP_TITLE}",
    page_icon="👥",
    layout=config.LAYOUT,  # pyright: ignore [reportArgumentType]
)


def render_users_and_rights_page() -> None:
    """Render management interface for Evals authorized users and roles."""
    st.title("👥 Accès Console & Droits")
    st.markdown(
        "Gestion des agents autorisés à accéder à la console Document IA via **ProConnect**."
    )

    # Formulaire d'ajout
    with st.expander("➕ Habiliter un nouvel agent", expanded=False):
        with st.form("add_user_form"):
            new_email = st.text_input(
                "Adresse email professionnelle",
                placeholder="prenom.nom@beta.gouv.fr",
            )
            new_role = st.selectbox(
                "Rôle",
                options=[r.value for r in UserRole],
                format_func=lambda x: "👑 Administrateur"
                if x == "admin"
                else "👤 Utilisateur",
            )
            submit_user = st.form_submit_button("Habiliter l'agent", type="primary")

            if submit_user:
                if not new_email or "@" not in new_email:
                    st.error("Veuillez saisir une adresse email valide.")
                else:
                    try:
                        add_evals_user(new_email, new_role)
                        st.success(
                            f"L'utilisateur '{new_email}' a été habilité avec succès."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")

    # Tableau des utilisateurs
    users = list_evals_users()
    if not users:
        st.info("Aucun utilisateur enregistré.")
    else:
        st.markdown(f"**{len(users)} utilisateur(s) habilité(s)**")
        col_email, col_role, col_status, col_login, col_actions = st.columns(
            [3, 2, 1.5, 2.5, 2]
        )
        col_email.markdown("**Email**")
        col_role.markdown("**Rôle**")
        col_status.markdown("**Statut**")
        col_login.markdown("**Dernière Connexion**")
        col_actions.markdown("**Actions**")
        st.markdown("---")

        for u in users:
            c_email, c_role, c_status, c_login, c_act = st.columns([3, 2, 1.5, 2.5, 2])
            with c_email:
                st.code(u.email, language="text")
            with c_role:
                badge = "👑 Admin" if u.role == "admin" else "👤 User"
                st.markdown(badge)
            with c_status:
                if u.is_active:
                    st.success("Actif")
                else:
                    st.error("Désactivé")
            with c_login:
                st.write(
                    u.last_login_at.strftime("%Y-%m-%d %H:%M")
                    if u.last_login_at
                    else "Jamais"
                )
            with c_act:
                btn_cols = st.columns(2)
                with btn_cols[0]:
                    toggle_label = "⛔" if u.is_active else "✅"
                    toggle_help = (
                        "Désactiver l'accès" if u.is_active else "Activer l'accès"
                    )
                    if st.button(
                        toggle_label,
                        key=f"toggle_active_{u.id}",
                        help=toggle_help,
                    ):
                        update_evals_user(u.email, is_active=not u.is_active)
                        st.rerun()
                with btn_cols[1]:
                    new_role = "user" if u.role == "admin" else "admin"
                    role_help = (
                        "Rétrograder en Utilisateur"
                        if u.role == "admin"
                        else "Promouvoir Administrateur"
                    )
                    if st.button("🔄", key=f"toggle_role_{u.id}", help=role_help):
                        update_evals_user(u.email, role=new_role)
                        st.rerun()
            st.divider()

    # Section Logs d'accès récents
    with st.expander("📜 Journal des accès récents (Audit Logs)", expanded=True):
        logs = list_recent_access_logs(limit=50)
        if not logs:
            st.info("Aucun log d'accès enregistré.")
        else:
            log_data = [
                {
                    "Date (UTC)": entry.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Email": entry.email,
                    "Action": entry.action,
                    "IP": entry.ip_address or "—",
                    "User Agent": (entry.user_agent[:40] + "...")
                    if entry.user_agent
                    else "—",
                }
                for entry in logs
            ]
            st.dataframe(pd.DataFrame(log_data), use_container_width=True)  # pyright: ignore [reportUnknownMemberType]


def main() -> None:
    enforce_page_auth(required_role="admin")
    render_users_and_rights_page()


if __name__ == "__main__":
    main()
