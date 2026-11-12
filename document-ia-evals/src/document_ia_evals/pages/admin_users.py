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


def _handle_role_change(email: str, widget_key: str) -> None:
    """Callback when an administrator updates a user role via dropdown."""
    new_role = st.session_state.get(widget_key)
    if new_role:
        try:
            update_evals_user(email, role=str(new_role))
            st.toast(f"Rôle de {email} mis à jour : {new_role}")
        except Exception as e:
            st.error(f"Erreur lors du changement de rôle : {e}")


def render_users_and_rights_page() -> None:
    """Render management interface for Evals authorized users and roles."""
    st.title("👥 Accès Console & Droits")
    st.markdown(
        "Gestion des agents autorisés à accéder à la console Document IA via **ProConnect**."
    )

    current_user_email = str(st.session_state.get("current_user_email", "")).lower()

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
                format_func=lambda x: (
                    "👑 Administrateur" if x == "admin" else "👤 Utilisateur"
                ),
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
            [3, 2.2, 1.2, 2, 1.6], vertical_alignment="center"
        )
        col_email.markdown("**Email**")
        col_role.markdown("**Rôle**")
        col_status.markdown("**Statut**")
        col_login.markdown("**Dernière Connexion**")
        col_actions.markdown("**Accès**")
        st.markdown("---")

        role_options = [UserRole.ADMIN.value, UserRole.USER.value]

        for u in users:
            c_email, c_role, c_status, c_login, c_act = st.columns(
                [3, 2.2, 1.2, 2, 1.6], vertical_alignment="center"
            )
            is_self = u.email.strip().lower() == current_user_email
            with c_email:
                st.code(u.email, language="text")
            with c_role:
                current_role_idx = (
                    role_options.index(u.role) if u.role in role_options else 1
                )
                st.selectbox(
                    "Rôle",
                    options=role_options,
                    index=current_role_idx,
                    key=f"role_select_{u.id}",
                    label_visibility="collapsed",
                    disabled=is_self,
                    format_func=lambda r: (
                        "👑 Administrateur" if r == "admin" else "👤 Utilisateur"
                    ),
                    on_change=_handle_role_change,
                    args=(u.email, f"role_select_{u.id}"),
                )
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
                toggle_label = "⛔ Désactiver" if u.is_active else "✅ Activer"
                toggle_help = (
                    "Vous ne pouvez pas modifier votre propre compte"
                    if is_self
                    else (
                        "Désactiver l'accès de cet agent"
                        if u.is_active
                        else "Réactiver l'accès de cet agent"
                    )
                )
                if st.button(
                    toggle_label,
                    key=f"toggle_active_{u.id}",
                    help=toggle_help,
                    disabled=is_self,
                    type="secondary" if u.is_active else "primary",
                    width="stretch",
                ):
                    try:
                        update_evals_user(u.email, is_active=not u.is_active)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")
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
            st.dataframe(pd.DataFrame(log_data))  # pyright: ignore [reportUnknownMemberType]


def main() -> None:
    enforce_page_auth(required_role="admin")
    render_users_and_rights_page()


if __name__ == "__main__":
    main()
