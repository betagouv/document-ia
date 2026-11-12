from urllib.parse import urljoin

import requests

from document_ia_api.api.contracts.api_key.api_key import (
    APIKeyCreatedResult,
    APIKeyResult,
    UpdateAPIKeyStatusRequest,
)
from document_ia_api.api.contracts.organization.organization import (
    CreateOrganizationRequest,
    OrganizationDetailsResult,
    OrganizationResult,
)
from document_ia_api.api.contracts.webhook.webhook import (
    CreateWebHookRequest,
    WebHookResult,
)
from document_ia_evals.utils.config import config

# --- DYNAMIC CONFIGURATION (SESSION ISOLATED) ---
# S4 / Issue #155: Remplacer la configuration globale mutable par un état propre à chaque session.
# Aucune configuration mutable n'est stockée au niveau du module Python.


def get_current_config() -> dict[str, str]:
    """Retrieve active Document IA API configuration isolated per Streamlit session.

    Falls back to config.DOCUMENT_IA_* if no custom environment is set in the current session.
    Never leaks the default server API key to a custom URL.
    """
    default_url: str = config.DOCUMENT_IA_BASE_URL.rstrip("/")
    default_key: str = config.DOCUMENT_IA_API_KEY or ""

    try:
        import streamlit as st

        if hasattr(st, "session_state"):
            custom_url = st.session_state.get("custom_document_ia_url")
            custom_key = st.session_state.get("custom_document_ia_api_key")
            if custom_url and custom_key:
                return {
                    "base_url": str(custom_url).rstrip("/"),
                    "api_key": str(custom_key),
                }
            if custom_url and str(custom_url).rstrip("/") != default_url:
                # Never leak default server API key to a custom URL
                return {
                    "base_url": str(custom_url).rstrip("/"),
                    "api_key": "",
                }
            if custom_key:
                return {
                    "base_url": default_url,
                    "api_key": str(custom_key),
                }
    except Exception:
        pass

    return {
        "base_url": default_url,
        "api_key": default_key,
    }


def configure_service(base_url: str, api_key: str) -> None:
    """Configure target Document IA environment for the current user session only."""
    clean_url = base_url.rstrip("/")
    try:
        import streamlit as st

        if hasattr(st, "session_state"):
            st.session_state["custom_document_ia_url"] = clean_url
            st.session_state["custom_document_ia_api_key"] = api_key
            return
    except Exception:
        pass


def _get_headers() -> dict[str, str]:
    cfg = get_current_config()
    return {
        "Accept": "application/json",
        "X-Api-Key": cfg["api_key"],
    }


def _get_url(path: str) -> str:
    cfg = get_current_config()
    return urljoin(cfg["base_url"] + "/", path.lstrip("/"))


# --- API METHODS ---


def list_organization() -> list[OrganizationResult]:
    """List all organizations."""
    url = _get_url("/api/v1/admin/organizations")

    response = requests.get(url, headers=_get_headers(), timeout=30)
    # On laisse l'erreur remonter pour que l'UI sache si l'URL est mauvaise
    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return [OrganizationResult.model_validate(item) for item in data]

    return []


def get_organization_details(organization_id: str) -> OrganizationDetailsResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}")

    response = requests.get(url, headers=_get_headers(), timeout=30)
    response.raise_for_status()

    data = response.json()
    return OrganizationDetailsResult.model_validate(data)


def create_organization(request: CreateOrganizationRequest) -> OrganizationResult:
    url = _get_url("/api/v1/admin/organizations")

    response = requests.post(
        url,
        headers=_get_headers(),
        json=request.model_dump(),
        timeout=30,
    )
    response.raise_for_status()

    return OrganizationResult.model_validate(response.json())


def delete_organization(organization_id: str) -> None:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}")
    requests.delete(url, headers=_get_headers(), timeout=30).raise_for_status()


def update_api_key_status(
    organization_id: str, api_key_id: str, request: UpdateAPIKeyStatusRequest
) -> APIKeyResult:
    url = _get_url(
        f"/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status"
    )

    response = requests.put(
        url,
        headers=_get_headers(),
        json=request.model_dump(),
        timeout=30,
    )
    response.raise_for_status()

    return APIKeyResult.model_validate(response.json())


def create_api_key(organization_id: str) -> APIKeyCreatedResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/api-keys")

    response = requests.post(url, headers=_get_headers(), timeout=30)
    response.raise_for_status()

    return APIKeyCreatedResult.model_validate(response.json())


def delete_api_key(organization_id: str, api_key_id: str) -> None:
    url = _get_url(
        f"/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}"
    )
    requests.delete(url, headers=_get_headers(), timeout=30).raise_for_status()


def get_webhook_details(organization_id: str) -> list[WebHookResult]:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/webhooks")

    response = requests.get(url, headers=_get_headers(), timeout=30)
    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return [WebHookResult.model_validate(item) for item in data]

    if isinstance(data, dict):
        return [WebHookResult.model_validate(data)]

    return []


def delete_webhook(organization_id: str, webhook_id: str) -> None:
    url = _get_url(
        f"/api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}"
    )
    requests.delete(url, headers=_get_headers(), timeout=30).raise_for_status()


def create_webhook(
    organization_id: str, request: CreateWebHookRequest
) -> WebHookResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/webhooks")

    response = requests.post(
        url,
        headers=_get_headers(),
        # SecretPayloadDict only serializes in JSON mode; the Python-mode dump
        # keeps a SecretDict instance that requests cannot encode.
        json=request.model_dump(mode="json"),
    )
    response.raise_for_status()

    return WebHookResult.model_validate(response.json())
