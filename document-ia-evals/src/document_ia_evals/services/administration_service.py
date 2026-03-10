from urllib.parse import urljoin

import requests

from document_ia_api.api.contracts.api_key.api_key import UpdateAPIKeyStatusRequest, APIKeyResult, APIKeyCreatedResult
from document_ia_api.api.contracts.organization.organization import (
    OrganizationResult,
    CreateOrganizationRequest,
    OrganizationDetailsResult,
)
from document_ia_api.api.contracts.webhook.webhook import WebHookResult, CreateWebHookRequest
from document_ia_evals.utils.config import config

# --- DYNAMIC CONFIGURATION ---
# On stocke la configuration active ici. Par défaut, c'est celle du fichier config.
_active_config = {
    "base_url": config.DOCUMENT_IA_BASE_URL,
    "api_key": config.DOCUMENT_IA_API_KEY
}


def configure_service(base_url: str, api_key: str):
    """Permet de changer l'environnement cible dynamiquement."""
    global _active_config
    # On s'assure qu'il n'y a pas de slash à la fin pour les joins propres
    _active_config["base_url"] = base_url.rstrip("/")
    _active_config["api_key"] = api_key


def get_current_config():
    """Récupère la config active pour l'affichage UI si besoin."""
    return _active_config


def _get_headers():
    return {
        "Accept": "application/json",
        "X-Api-Key": _active_config["api_key"],
    }


def _get_url(path: str):
    return urljoin(_active_config["base_url"], path)


# --- API METHODS ---

def list_organization() -> list[OrganizationResult]:
    """List all organizations."""
    url = _get_url("/api/v1/admin/organizations")

    response = requests.get(url, headers=_get_headers())
    # On laisse l'erreur remonter pour que l'UI sache si l'URL est mauvaise
    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return [OrganizationResult.model_validate(item) for item in data]

    return []


def get_organization_details(organization_id: str) -> OrganizationDetailsResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}")

    response = requests.get(url, headers=_get_headers())
    response.raise_for_status()

    data = response.json()
    return OrganizationDetailsResult.model_validate(data)


def create_organization(request: CreateOrganizationRequest) -> OrganizationResult:
    url = _get_url("/api/v1/admin/organizations")

    response = requests.post(
        url,
        headers=_get_headers(),
        json=request.model_dump(),
    )
    response.raise_for_status()

    return OrganizationResult.model_validate(response.json())


def delete_organization(organization_id: str) -> None:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}")
    requests.delete(url, headers=_get_headers()).raise_for_status()


def update_api_key_status(organization_id: str, api_key_id: str, request: UpdateAPIKeyStatusRequest) -> APIKeyResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status")

    response = requests.put(
        url,
        headers=_get_headers(),
        json=request.model_dump(),
    )
    response.raise_for_status()

    return APIKeyResult.model_validate(response.json())


def create_api_key(organization_id: str) -> APIKeyCreatedResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/api-keys")

    response = requests.post(url, headers=_get_headers())
    response.raise_for_status()

    return APIKeyCreatedResult.model_validate(response.json())


def delete_api_key(organization_id: str, api_key_id: str) -> None:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}")
    requests.delete(url, headers=_get_headers()).raise_for_status()


def get_webhook_details(organization_id: str) -> list[WebHookResult]:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/webhooks")

    response = requests.get(url, headers=_get_headers())
    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return [WebHookResult.model_validate(item) for item in data]

    if isinstance(data, dict):
        return [WebHookResult.model_validate(data)]

    return []


def delete_webhook(organization_id: str, webhook_id: str) -> None:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}")
    requests.delete(url, headers=_get_headers()).raise_for_status()


def create_webhook(organization_id: str, request: CreateWebHookRequest) -> WebHookResult:
    url = _get_url(f"/api/v1/admin/organizations/{organization_id}/webhooks")

    response = requests.post(
        url,
        headers=_get_headers(),
        json=request.model_dump(),
    )
    response.raise_for_status()

    return WebHookResult.model_validate(response.json())
