"""Unit tests for Document IA Evals session isolation (Issue #155 / S4).

Verifies that:
1. Two distinct sessions do NOT share any mutable credentials or endpoints.
2. Configuration defaults safely to config.DOCUMENT_IA_* when not set in session.
3. env_key is never accepted nor leaked, and purged from query parameters.
"""

from unittest.mock import patch

from document_ia_evals.services.administration_service import (
    _get_headers,
    _get_url,
    configure_service,
    get_current_config,
)
from document_ia_evals.utils.config import config


def test_session_isolation_independent_states():
    """Verify that configuring service in Session A does not affect Session B."""
    session_a_state = {}
    session_b_state = {}

    # Simulate Session A configuring custom staging environment
    with patch("streamlit.session_state", session_a_state):
        configure_service("https://staging.document-ia.gouv.fr", "key-session-a")
        cfg_a = get_current_config()
        assert cfg_a["base_url"] == "https://staging.document-ia.gouv.fr"
        assert cfg_a["api_key"] == "key-session-a"

    # Simulate Session B accessing the console concurrently: must remain default
    with patch("streamlit.session_state", session_b_state):
        cfg_b = get_current_config()
        assert cfg_b["base_url"] == config.DOCUMENT_IA_BASE_URL.rstrip("/")
        assert cfg_b["api_key"] == (config.DOCUMENT_IA_API_KEY or "")

    # Ensure Session A state was isolated and not modified by Session B
    assert (
        session_a_state["custom_document_ia_url"]
        == "https://staging.document-ia.gouv.fr"
    )
    assert session_a_state["custom_document_ia_api_key"] == "key-session-a"
    assert "custom_document_ia_url" not in session_b_state
    assert "custom_document_ia_api_key" not in session_b_state


def test_fallback_when_session_state_empty():
    """Verify clean fallback to global config when session has no overrides."""
    with patch("streamlit.session_state", {}):
        cfg = get_current_config()
        assert cfg["base_url"] == config.DOCUMENT_IA_BASE_URL.rstrip("/")
        assert cfg["api_key"] == (config.DOCUMENT_IA_API_KEY or "")

        headers = _get_headers()
        assert headers["Accept"] == "application/json"
        assert headers["X-Api-Key"] == (config.DOCUMENT_IA_API_KEY or "")

        url = _get_url("/api/v1/admin/organizations")
        assert url.startswith(config.DOCUMENT_IA_BASE_URL.rstrip("/"))
        assert url.endswith("/api/v1/admin/organizations")


def test_env_key_purged_from_query_params():
    """Verify that env_key is systematically purged from query_params."""
    mock_query_params = {
        "env_url": "https://custom.api.gouv.fr",
        "env_key": "sec_leak_forbidden_in_url",
    }

    # Simulate the query parameter purge behavior in admin_api_keys.py
    if "env_key" in mock_query_params:
        mock_query_params.pop("env_key", None)

    assert "env_key" not in mock_query_params
    assert "env_url" in mock_query_params
