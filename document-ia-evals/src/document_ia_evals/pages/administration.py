from typing import Any

import pandas as pd
import streamlit as st
from document_ia_evals.services.administration_service import (
    list_organization,
    create_organization,
    delete_organization,
    get_organization_details,
    update_api_key_status,
    create_api_key,
    delete_api_key,
    get_webhook_details,
    delete_webhook,
    create_webhook,
    configure_service,
    get_current_config,
)
from document_ia_evals.utils.config import config
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.organization.enum.platform_role import PlatformRole

from document_ia_api.api.contracts.api_key.api_key import UpdateAPIKeyStatusRequest, APIKeyCreatedResult
from document_ia_api.api.contracts.organization.organization import CreateOrganizationRequest, OrganizationDetailsResult
from document_ia_api.api.contracts.webhook.webhook import CreateWebHookRequest

st.set_page_config(
    page_title=f"Administration | {config.APP_TITLE}",
    page_icon="📊",
    layout=config.LAYOUT,
)


def load_env_from_params() -> None:
    qp = st.query_params
    env_url = qp.get("env_url")
    env_key = qp.get("env_key")

    if env_url and env_key:
        configure_service(env_url, env_key)


load_env_from_params()


@st.dialog("Configuration de l'environnement")
def dialog_configure_env() -> None:
    st.write("Définissez l'environnement cible. Ces informations seront conservées dans l'URL.")

    current = get_current_config()

    with st.form("env_config"):
        new_url = st.text_input("Backend URL", value=current.get("base_url", ""), key="env_config_url")
        new_key = st.text_input(
            "Admin API Key",
            value=current.get("api_key", ""),
            type="password",
            key="env_config_key",
        )

        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Sauvegarder", type="primary", use_container_width=True)
        with col2:
            reset = st.form_submit_button("Réinitialiser (Défaut)", type="secondary", use_container_width=True)

        if submitted:
            if new_url and new_key:
                st.query_params["env_url"] = new_url
                st.query_params["env_key"] = new_key
                st.success("Configuration sauvegardée ! Rechargement...")
                st.rerun()
            else:
                st.error("L'URL et la Clé sont requises.")

        if reset:
            st.query_params.clear()
            configure_service(config.DOCUMENT_IA_BASE_URL, config.DOCUMENT_IA_API_KEY)

            st.session_state.pop("env_config_url", None)
            st.session_state.pop("env_config_key", None)

            st.success("Retour à la configuration par défaut.")
            st.rerun()


@st.dialog("Créer une nouvelle organisation")
def dialog_add_organization() -> None:
    st.write("Remplissez les informations ci-dessous pour déclarer une nouvelle organisation.")

    with st.form("create_org_form"):
        name = st.text_input("Nom de l'organisation", placeholder="Ex: Acme Corp")
        email = st.text_input("Email de contact", placeholder="Ex: ops@acme.corp")

        roles = [r.value for r in PlatformRole]
        role_selection = st.selectbox("Rôle Plateforme", options=roles, index=0)

        submitted = st.form_submit_button("Créer l'organisation", type="primary")

        if submitted:
            if not name or not email:
                st.error("Le nom et l'email sont obligatoires.")
            else:
                try:
                    selected_role_enum = None
                    for r in PlatformRole:
                        if r.value == role_selection:
                            selected_role_enum = r
                            break

                    req = CreateOrganizationRequest(
                        name=name,
                        contact_email=email,
                        platform_role=selected_role_enum or role_selection,
                    )

                    new_org = create_organization(req)

                    st.success(f"Organisation '{new_org.name}' créée avec succès !")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur lors de la création : {str(e)}")


def render_header(orgs: list[Any]):
    col_title, col_config = st.columns([0.85, 0.15], vertical_alignment="center")
    with col_title:
        st.title("Administration")
    with col_config:
        is_custom = "env_url" in st.query_params
        btn_type = "primary" if is_custom else "secondary"
        help_text = "Environnement personnalisé actif" if is_custom else "Config par défaut"
        if st.button("⚙️ Env", type=btn_type, help=help_text, use_container_width=True):
            dialog_configure_env()

    st.caption("Gestion des accès et des configurations par organisation.")

    if "env_url" in st.query_params:
        st.info(f"🌐 Connecté à : `{st.query_params['env_url']}`", icon="🔗")

    if not orgs:
        return None

    org_map = {org.name: org for org in orgs}

    c_sel, c_add = st.columns([0.85, 0.15], vertical_alignment="bottom")

    with c_sel:
        default_index = 0
        if (
                "selected_org_name" in st.session_state
                and st.session_state["selected_org_name"] in org_map
        ):
            default_index = list(org_map.keys()).index(st.session_state["selected_org_name"])

        selected_name = st.selectbox(
            "🏢 Organisation active",
            options=list(org_map.keys()),
            index=default_index if org_map else None,
            label_visibility="visible",
        )

    with c_add:
        if st.button("➕", help="Ajouter une organisation"):
            dialog_add_organization()

    st.session_state["selected_org_name"] = selected_name
    return org_map.get(selected_name) if selected_name else None


@st.dialog("Supprimer l'organisation")
def render_delete_org_dialog(org) -> None:
    st.warning(
        f"Vous êtes sur le point de supprimer l'organisation **{org.name}**.",
        icon="⚠️",
    )
    st.write(
        "Cette action supprimera également toutes les clés API associées et les webhooks configurés pour cette organisation. "
        "Cette opération est irréversible.",
    )

    col_confirm = st.columns(1)[0]
    with col_confirm:
        if st.button("Confirmer la suppression", type="primary", use_container_width=True):
            try:
                delete_organization(str(org.id))
                st.success(f"Organisation '{org.name}' supprimée avec succès.")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de la suppression : {str(e)}")


def render_org_details(org_details: OrganizationDetailsResult) -> None:
    st.markdown(f"### ℹ️ Détails de l'organisation : {org_details.name}")

    org_data = {
        "ID": org_details.id,
        "Nom": org_details.name,
        "Email Contact": org_details.contact_email,
        "Rôle": str(org_details.platform_role.value)
        if hasattr(org_details.platform_role, "value")
        else str(org_details.platform_role),
        "Créé le": org_details.created_at,
        "Dernière MAJ": org_details.updated_at,
    }

    df = pd.DataFrame([org_data])
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "ID": st.column_config.TextColumn("ID", help="Identifiant unique"),
            "Email Contact": st.column_config.LinkColumn(
                "Email Contact", display_text=org_details.contact_email
            ),
        },
    )

    st.write("")
    col_del, _ = st.columns([1, 3])
    with col_del:
        if st.button("🗑️ Supprimer cette organisation", type="secondary"):
            render_delete_org_dialog(org_details)

@st.dialog("Nouvelle clé API générée")
def _show_created_api_key_dialog(result: APIKeyCreatedResult) -> None:
    st.success("La clé API a été générée avec succès.")
    st.write(
        "Voici la valeur **complète** de la clé API.\n\n"
        "**Une fois cette fenêtre fermée, il ne sera plus possible de la visualiser à nouveau.**\n\n"
        "Copiez-la immédiatement et stockez-la dans un endroit sûr (gestionnaire de secrets, coffre-fort, etc.).",
    )
    st.code(result.key, language="text")

    if st.button("J'ai copié cette clé", type="primary", use_container_width=True):
        st.rerun()


@st.dialog("Supprimer la clé API")
def _show_delete_api_key_dialog(
        org_details: OrganizationDetailsResult, key_id: str, key_prefix: str
) -> None:
    st.warning(
        f"Vous êtes sur le point de supprimer la clé API avec le préfixe **{key_prefix}**.",
        icon="⚠️",
    )
    st.write(
        "Cette action est définitive. La clé ne pourra plus être utilisée pour authentifier des appels à l'API.",
    )

    col_confirm = st.columns(1)[0]
    with col_confirm:
        if st.button("Confirmer la suppression", type="primary", use_container_width=True):
            try:
                delete_api_key(str(org_details.id), key_id)
                st.success("Clé API supprimée avec succès.")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de la suppression de la clé API : {e}")


@st.dialog("Supprimer le webhook")
def _show_delete_webhook_dialog(
        org_details: OrganizationDetailsResult, webhook_id: str, webhook_url: str
) -> None:
    st.warning(
        "Vous êtes sur le point de supprimer le webhook suivant:",
        icon="⚠️",
    )
    st.code(webhook_url, language="text")
    st.write(
        "Cette action est définitive. Ce webhook ne sera plus appelé pour cette organisation.",
    )

    col_confirm = st.columns(1)[0]
    with col_confirm:
        if st.button("Confirmer la suppression", type="primary", use_container_width=True):
            try:
                delete_webhook(str(org_details.id), webhook_id)
                st.success("Webhook supprimé avec succès.")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de la suppression du webhook : {e}")


@st.dialog("Ajouter un webhook")
def _dialog_add_webhook(org_details: OrganizationDetailsResult) -> None:
    st.write("Configurez un nouvel endpoint webhook pour cette organisation.")

    if "webhook_rows_ids" not in st.session_state:
        st.session_state.webhook_rows_ids = [0]

    if "webhook_next_row_id" not in st.session_state:
        st.session_state.webhook_next_row_id = 1

    def add_row() -> None:
        st.session_state.webhook_rows_ids.append(st.session_state.webhook_next_row_id)
        st.session_state.webhook_next_row_id += 1

    def remove_row(row_id_to_remove: int) -> None:
        if len(st.session_state.webhook_rows_ids) > 0:
            st.session_state.webhook_rows_ids.remove(row_id_to_remove)
            st.session_state.pop(f"wh_key_{row_id_to_remove}", None)
            st.session_state.pop(f"wh_val_{row_id_to_remove}", None)

    url = st.text_input(
        "URL du webhook",
        placeholder="https://example.com/webhook",
        key="new_webhook_url",
    )

    st.markdown("**Headers HTTP (optionnels)**")
    st.caption("Ajoutez des paires clé/valeur qui seront envoyées en header avec chaque appel.")

    for row_id in st.session_state.webhook_rows_ids:
        c1, c2, c3 = st.columns([3, 3, 1], vertical_alignment="bottom")

        with c1:
            label_key = "Clé" if row_id == st.session_state.webhook_rows_ids[0] else ""
            st.text_input(
                label_key,
                key=f"wh_key_{row_id}",
                placeholder="Authorization",
                label_visibility="visible" if label_key else "collapsed",
            )

        with c2:
            label_val = "Valeur" if row_id == st.session_state.webhook_rows_ids[0] else ""
            st.text_input(
                label_val,
                key=f"wh_val_{row_id}",
                placeholder="Bearer ...",
                label_visibility="visible" if label_val else "collapsed",
            )

        with c3:
            st.button("🗑️", key=f"rm_{row_id}", on_click=remove_row, args=(row_id,))

    st.button("➕ Ajouter un header", on_click=add_row)

    st.markdown("---")

    if st.button("Créer le webhook", type="primary", use_container_width=True):
        headers_dict: dict[str, str] = {}

        for r_id in st.session_state.webhook_rows_ids:
            k = st.session_state.get(f"wh_key_{r_id}", "").strip()
            v = st.session_state.get(f"wh_val_{r_id}", "").strip()
            if k:
                headers_dict[k] = v

        if not url:
            st.error("L'URL du webhook est obligatoire.")
        else:
            try:
                req = CreateWebHookRequest(url=url, headers=headers_dict)
                create_webhook(str(org_details.id), req)
                st.success("Webhook créé avec succès.")

                st.session_state.pop("webhook_rows_ids", None)
                st.session_state.pop("webhook_next_row_id", None)

                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de la création du webhook : {e}")


def render_api_keys_tab(org_details: OrganizationDetailsResult) -> None:
    st.subheader("Clés API")

    if st.button("➕ Générer une nouvelle clé API"):
        try:
            created = create_api_key(str(org_details.id))
            _show_created_api_key_dialog(created)
        except Exception as e:
            st.error(f"Erreur lors de la création de la clé API : {e}")

    keys = org_details.api_keys

    if not keys:
        st.warning("Aucune clé API pour cette organisation.")
        return

    h1, h2, h3, h4, h5, h6 = st.columns([2, 2, 2, 2, 1.5, 1.5])
    h1.markdown("**ID**")
    h2.markdown("**Préfixe**")
    h3.markdown("**Statut**")
    h4.markdown("**Créée / Mise à jour**")
    h5.markdown("**Actions**")
    h6.markdown("**Supprimer**")
    st.markdown("---")

    for key in keys:
        c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 1.5, 1.5])
        with c1:
            st.code(key.id, language="text")
        with c2:
            st.code(key.prefix, language="text")
        with c3:
            if key.status == ApiKeyStatus.ACTIVE:
                st.markdown(
                    "<span style='background-color:#22c55e20;color:#16a34a;padding:4px 8px;border-radius:999px;"
                    "font-weight:600;font-size:0.85rem;'>Active</span>",
                    unsafe_allow_html=True,
                )
            elif key.status == ApiKeyStatus.REVOKED:
                st.markdown(
                    "<span style='background-color:#fee2e2;color:#b91c1c;padding:4px 8px;border-radius:999px;"
                    "font-weight:600;font-size:0.85rem;'>Revoked</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.write(str(key.status))
        with c4:
            st.write(f"Créée: {key.created_at}")
            st.caption(f"MAJ: {key.updated_at}")
        with c5:
            if key.status == ApiKeyStatus.ACTIVE:
                label = "⏸️ Pause"
                new_status = ApiKeyStatus.REVOKED
            elif key.status == ApiKeyStatus.REVOKED:
                label = "▶️ Activer"
                new_status = ApiKeyStatus.ACTIVE
            else:
                label = None
                new_status = None

            if label and st.button(label, key=f"toggle_{key.id}", use_container_width=True):
                try:
                    req = UpdateAPIKeyStatusRequest(status=new_status)
                    update_api_key_status(
                        organization_id=str(org_details.id),
                        api_key_id=key.id,
                        request=req,
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur lors de la mise à jour du statut: {e}")
        with c6:
            if st.button("🗑️", key=f"delete_{key.id}", use_container_width=True):
                _show_delete_api_key_dialog(org_details, key.id, key.prefix)
        st.divider()


def render_webhooks_tab(org_details: OrganizationDetailsResult) -> None:
    st.subheader("Webhooks")

    if st.button("➕ Ajouter un webhook"):
        _dialog_add_webhook(org_details)

    try:
        webhooks = get_webhook_details(str(org_details.id))
    except Exception as e:
        st.error(f"Erreur lors du chargement des webhooks : {e}")
        return

    if not webhooks:
        st.info("Aucun webhook configuré pour cette organisation.")
        return

    st.markdown("**Liste des webhooks configurés**")

    h1, h2, h3, h4, h5 = st.columns([2, 3, 3, 2, 1.5])
    h1.markdown("**ID**")
    h2.markdown("**URL**")
    h3.markdown("**Headers**")
    h4.markdown("**Créé / MAJ**")
    h5.markdown("**Supprimer**")
    st.markdown("---")

    for hook in webhooks:
        c1, c2, c3, c4, c5 = st.columns([2, 3, 3, 2, 1.5])
        with c1:
            st.code(hook.id, language="text")
        with c2:
            st.code(hook.url, language="text")
        with c3:
            headers_str = ", ".join(f"{k}: {v}" for k, v in hook.headers.items()) if hook.headers else "—"
            st.write(headers_str)
        with c4:
            st.write(f"Créé: {hook.created_at}")
            st.caption(f"MAJ: {hook.updated_at}")
        with c5:
            if st.button("🗑️", key=f"delete_webhook_{hook.id}", use_container_width=True):
                _show_delete_webhook_dialog(org_details, hook.id, hook.url)
        st.divider()


def main() -> None:
    with st.spinner("Chargement des organisations..."):
        try:
            orgs = list_organization()
        except Exception as e:
            st.error(f"Erreur de connexion au service d'administration : {str(e)}")
            st.info("Vérifiez votre configuration d'environnement via le bouton '⚙️ Env' en haut à droite.")
            orgs = []

    selected_org = render_header(orgs)

    if not orgs and not selected_org:
        if not orgs:
            st.warning("Aucune organisation trouvée ou impossible de joindre le backend.")
        else:
            st.info("Commencez par en créer une via le bouton '+' ci-dessus.")
        return

    if selected_org:
        try:
            org_details = get_organization_details(str(selected_org.id))
        except Exception as e:
            st.error(f"Impossible de charger les détails de l'organisation : {str(e)}")
            return

        render_org_details(org_details)

        st.write("")

        tab_api, tab_hooks = st.tabs(["🔑 Clés API", "🪝 Webhooks"])

        with tab_api:
            render_api_keys_tab(org_details)

        with tab_hooks:
            render_webhooks_tab(org_details)


if __name__ == "__main__":
    main()
