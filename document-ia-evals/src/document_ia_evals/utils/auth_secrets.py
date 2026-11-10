"""Bootstrap utility to configure Streamlit OIDC authentication with ProConnect.

This script ensures Streamlit's native OIDC authentication is properly configured
at startup (both on Scalingo and during local development) without hardcoding secrets,
and bridges DINUM / ProConnect specificities:
1. Strips unsupported 'prompt=select_account' query parameters.
2. Fetches user claims (email, given_name, usual_name) from ProConnect's UserInfo endpoint
   via back-channel HTTP request, because ProConnect's id_token is intentionally minimal
   and contains no personal data.
"""

import base64
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from document_ia_evals.utils.config import config

logger = logging.getLogger(__name__)


def fetch_proconnect_userinfo(client: Any, token: dict[str, Any]) -> dict[str, Any]:
    """Fetch user profile from ProConnect userinfo_endpoint.

    According to the DINUM / ProConnect specification:
    - The id_token only contains technical claims (sub, aud, iss, acr, amr, nonce).
    - User claims (email, given_name, usual_name, siret...) MUST be queried
      from the UserInfo endpoint using the Bearer access token.
    - UserInfo responses may be returned as either JSON or signed JWT.
    """
    if not isinstance(token, dict) or not token.get("access_token"):
        return {}

    try:
        metadata = client.load_server_metadata()
        userinfo_endpoint = metadata.get("userinfo_endpoint")
        if not userinfo_endpoint:
            return {}

        resp = client.get(userinfo_endpoint, token=token)
        if getattr(resp, "status_code", None) != 200:
            logger.warning(
                "ProConnect userinfo endpoint returned HTTP %s: %s",
                getattr(resp, "status_code", "unknown"),
                getattr(resp, "text", ""),
            )
            return {}

        data: dict[str, Any] | None = None
        # 1. Attempt standard JSON parsing
        try:
            data = resp.json()
        except Exception:
            pass

        # 2. If not a dict, check for signed JWT payload (e.g. eyJhbGciOi...)
        if not isinstance(data, dict):
            text = str(getattr(resp, "text", "")).strip().strip('"')
            if text.count(".") == 2:
                payload_part = text.split(".")[1]
                # Fix base64url padding
                payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
                decoded_bytes = base64.urlsafe_b64decode(payload_part.encode("utf-8"))
                data = json.loads(decoded_bytes.decode("utf-8"))

        if isinstance(data, dict):
            # Compute composite name if not explicitly set
            if not data.get("name"):
                given = data.get("given_name")
                family = data.get("usual_name") or data.get("family_name")
                if given or family:
                    data["name"] = " ".join([str(p) for p in (given, family) if p])
            return data
    except Exception as exc:
        logger.warning("Error querying ProConnect userinfo endpoint: %s", exc)

    return {}


def patch_streamlit_oidc() -> None:
    """Ensure Streamlit OIDC implementation is 100% compliant with ProConnect.

    1. Removes 'prompt=select_account' from client_kwargs.
    2. Enriches 'userinfo' in TornadoOAuth2App.authorize_access_token with
       data fetched from the UserInfo endpoint.
    """
    # 1. Patch Tornado create_oauth_client to drop prompt
    try:
        import streamlit.web.server.oauth_authlib_routes as routes

        if not getattr(routes, "_proconnect_prompt_patched", False):
            original_create_oauth_client = routes.create_oauth_client

            def safe_create_oauth_client(provider: str):
                client, redirect_uri = original_create_oauth_client(provider)
                if provider == "proconnect" and hasattr(client, "client_kwargs"):
                    client.client_kwargs.pop("prompt", None)
                return client, redirect_uri

            routes.create_oauth_client = safe_create_oauth_client
            setattr(routes, "_proconnect_prompt_patched", True)
    except Exception as e:
        logger.debug("[auth_secrets] Note: could not patch Tornado oauth routes: %s", e)

    # 2. Patch TornadoOAuth2App.authorize_access_token to fetch userinfo
    try:
        from streamlit.web.server.oidc_mixin import TornadoOAuth2App

        if not getattr(TornadoOAuth2App, "_proconnect_patched", False):
            original_tornado_authorize = TornadoOAuth2App.authorize_access_token

            def patched_tornado_authorize_access_token(self, request_handler, **kwargs):
                token = original_tornado_authorize(self, request_handler, **kwargs)
                if isinstance(token, dict):
                    userinfo = dict(token.get("userinfo") or {})
                    if not userinfo.get("email"):
                        extra_claims = fetch_proconnect_userinfo(self, token)
                        if extra_claims:
                            userinfo.update(extra_claims)
                            token["userinfo"] = userinfo
                return token

            TornadoOAuth2App.authorize_access_token = patched_tornado_authorize_access_token
            setattr(TornadoOAuth2App, "_proconnect_patched", True)
    except Exception as e:
        logger.debug("[auth_secrets] Note: could not patch TornadoOAuth2App: %s", e)

    # 3. Patch Starlette create_oauth_client to drop prompt
    try:
        import streamlit.web.server.starlette.starlette_auth_routes as s_routes

        if not getattr(s_routes, "_proconnect_prompt_patched", False):
            original_s_create = s_routes._create_oauth_client  # pyright: ignore [reportPrivateUsage]

            def safe_s_create_oauth_client(provider: str):
                client, redirect_uri = original_s_create(provider)
                if provider == "proconnect" and hasattr(client, "client_kwargs"):
                    client.client_kwargs.pop("prompt", None)
                return client, redirect_uri

            s_routes._create_oauth_client = safe_s_create_oauth_client  # pyright: ignore [reportPrivateUsage]
            setattr(s_routes, "_proconnect_prompt_patched", True)
    except Exception:
        pass

    # 4. Patch StarletteOAuth2App.authorize_access_token if available
    try:
        from authlib.integrations.starlette_client import StarletteOAuth2App

        if not getattr(StarletteOAuth2App, "_proconnect_patched", False):
            original_starlette_authorize = StarletteOAuth2App.authorize_access_token

            async def patched_starlette_authorize_access_token(self, request, **kwargs):
                token = await original_starlette_authorize(self, request, **kwargs)
                if isinstance(token, dict):
                    userinfo = dict(token.get("userinfo") or {})
                    if not userinfo.get("email"):
                        extra_claims = fetch_proconnect_userinfo(self, token)
                        if extra_claims:
                            userinfo.update(extra_claims)
                            token["userinfo"] = userinfo
                return token

            StarletteOAuth2App.authorize_access_token = patched_starlette_authorize_access_token
            setattr(StarletteOAuth2App, "_proconnect_patched", True)
    except Exception:
        pass


# Backwards compatibility alias
patch_streamlit_oidc_prompt = patch_streamlit_oidc


def generate_secrets_toml(target_path: Path | None = None) -> Path | None:
    """Generate or update .streamlit/secrets.toml from configuration/environment.

    Returns the path to the written file, or None if bypass is active without credentials.
    """
    patch_streamlit_oidc()
    if target_path is None:
        target_path = config.ROOT_DIR / ".streamlit" / "secrets.toml"

    # In local bypass mode with no client id provided, we don't need real OIDC secrets
    if config.AUTH_BYPASS_LOCAL and not config.PROCONNECT_CLIENT_ID:
        print(
            "[auth_secrets] AUTH_BYPASS_LOCAL=true and no PROCONNECT_CLIENT_ID set. Skipping secrets generation."
        )
        return None

    client_id = config.PROCONNECT_CLIENT_ID or os.getenv("PROCONNECT_CLIENT_ID", "")
    client_secret = config.PROCONNECT_CLIENT_SECRET or os.getenv(
        "PROCONNECT_CLIENT_SECRET", ""
    )
    metadata_url = config.PROCONNECT_METADATA_URL or os.getenv(
        "PROCONNECT_METADATA_URL",
        "https://fca.integ01.dev-agentconnect.fr/api/v2/.well-known/openid-configuration",
    )
    redirect_uri = config.PROCONNECT_REDIRECT_URI or os.getenv(
        "PROCONNECT_REDIRECT_URI",
        "http://localhost:8501/oauth2callback",
    )
    cookie_secret = config.PROCONNECT_COOKIE_SECRET or os.getenv(
        "PROCONNECT_COOKIE_SECRET"
    )
    if not cookie_secret:
        # Generate an ephemeral secret if not provided
        cookie_secret = secrets.token_hex(32)

    scopes = config.PROCONNECT_SCOPES or os.getenv(
        "PROCONNECT_SCOPES", "openid email profile"
    )

    # Format TOML content
    toml_content = f"""# Auto-generated by auth_secrets.py - DO NOT COMMIT SECRETS TO GIT
[auth]
redirect_uri = "{redirect_uri}"
cookie_secret = "{cookie_secret}"

[auth.proconnect]
client_id = "{client_id}"
client_secret = "{client_secret}"
server_metadata_url = "{metadata_url}"
client_kwargs = {{ scope = "{scopes}" }}
"""

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(toml_content, encoding="utf-8")
    print(f"[auth_secrets] Successfully wrote OIDC configuration to {target_path}")
    return target_path


# Automatically patch when module is loaded
patch_streamlit_oidc()


if __name__ == "__main__":
    generate_secrets_toml()
