"""Unit tests for ProConnect authentication and RBAC service."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from document_ia_evals.database.models import Base, EvalsAccessLog, EvalsUser, UserRole
from document_ia_evals.services.auth_service import (
    add_evals_user,
    delete_evals_user,
    list_evals_users,
    list_recent_access_logs,
    record_login_event,
    record_logout,
    update_evals_user,
    verify_user_access,
)
from document_ia_evals.utils.auth_secrets import (
    fetch_proconnect_userinfo,
    generate_secrets_toml,
    patch_streamlit_oidc,
    patch_streamlit_oidc_prompt,
)


@pytest.fixture
def in_memory_db():
    """Create an isolated in-memory SQLite database for authentication testing."""
    engine = create_engine("sqlite:///:memory:")
    from typing import cast
    from sqlalchemy import Table

    Base.metadata.create_all(
        bind=engine,
        tables=cast(list[Table], [EvalsUser.__table__, EvalsAccessLog.__table__]),
    )
    Session = sessionmaker(bind=engine)

    @contextmanager
    def mock_get_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    with patch(
        "document_ia_evals.services.auth_service.get_session",
        side_effect=mock_get_session,
    ):
        yield mock_get_session


def test_generate_secrets_toml(tmp_path: Path) -> None:
    """Test generating .streamlit/secrets.toml from configuration."""
    target_file = tmp_path / "secrets.toml"

    with patch("document_ia_evals.utils.auth_secrets.config") as mock_config:
        mock_config.AUTH_BYPASS_LOCAL = False
        mock_config.PROCONNECT_CLIENT_ID = "test-client-id"
        mock_config.PROCONNECT_CLIENT_SECRET = "test-client-secret"
        mock_config.PROCONNECT_METADATA_URL = "https://fca.integ01.dev-agentconnect.fr/api/v2/.well-known/openid-configuration"
        mock_config.PROCONNECT_REDIRECT_URI = "http://localhost:8501/oauth2callback"
        mock_config.PROCONNECT_COOKIE_SECRET = "test-cookie-secret-1234567890"
        mock_config.PROCONNECT_SCOPES = "openid email profile"

        result_path = generate_secrets_toml(target_path=target_file)
        assert result_path is not None
        assert result_path.exists()

        content = result_path.read_text()
        assert "[auth]" in content
        assert 'client_id = "test-client-id"' in content
        assert 'client_secret = "test-client-secret"' in content
        assert 'redirect_uri = "http://localhost:8501/oauth2callback"' in content
        assert 'cookie_secret = "test-cookie-secret-1234567890"' in content
        assert 'scope = "openid email profile"' in content


def test_generate_secrets_toml_bypass_mode(tmp_path: Path) -> None:
    """Test that secrets generation is skipped if bypass is active without credentials."""
    target_file = tmp_path / "secrets.toml"

    with patch("document_ia_evals.utils.auth_secrets.config") as mock_config:
        mock_config.AUTH_BYPASS_LOCAL = True
        mock_config.PROCONNECT_CLIENT_ID = None

        result_path = generate_secrets_toml(target_path=target_file)
        assert result_path is None
        assert not target_file.exists()


def test_verify_user_access_unknown_user(in_memory_db) -> None:
    """Test access verification for an unregistered user (read-only, no logs)."""
    is_allowed, user, reason = verify_user_access("unknown@beta.gouv.fr")

    assert not is_allowed
    assert user is None
    assert "Accès refusé" in reason

    # verify_user_access is read-only and does not write access logs
    logs = list_recent_access_logs()
    assert len(logs) == 0


def test_verify_user_access_disabled_user(in_memory_db) -> None:
    """Test access verification for a deactivated user (read-only, no logs)."""
    user = add_evals_user("inactive@beta.gouv.fr", role="user")
    update_evals_user(user.email, is_active=False)

    is_allowed, verified_user, reason = verify_user_access("inactive@beta.gouv.fr")

    assert not is_allowed
    assert verified_user is None
    assert "désactivé" in reason

    logs = list_recent_access_logs()
    assert len(logs) == 0


def test_verify_user_access_success_is_read_only(in_memory_db) -> None:
    """Test successful user authorization check does NOT flood audit logs (e.g. on F5)."""
    add_evals_user("nicolas.sagon@beta.gouv.fr", role="admin")

    # Simulate 5 page refreshes (F5) or reruns
    for _ in range(5):
        is_allowed, user, reason = verify_user_access("nicolas.sagon@beta.gouv.fr")
        assert is_allowed
        assert user is not None
        assert user.email == "nicolas.sagon@beta.gouv.fr"

    # Exactly 0 logs created by page visits/reruns
    logs = list_recent_access_logs()
    assert len(logs) == 0


def test_record_login_event_success(in_memory_db) -> None:
    """Test recording login_success event upon OAuth2 callback."""
    add_evals_user("agent@beta.gouv.fr", role="user")
    record_login_event("agent@beta.gouv.fr", ip_address="192.168.1.1", user_agent="Mozilla/5.0")

    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "login_success"
    assert logs[0].email == "agent@beta.gouv.fr"
    assert logs[0].ip_address == "192.168.1.1"
    assert logs[0].user_agent == "Mozilla/5.0"


def test_record_login_event_denials(in_memory_db) -> None:
    """Test recording access denial logs during OAuth2 callback."""
    # 1. Unknown user
    record_login_event("stranger@beta.gouv.fr")
    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "access_denied_unknown_user"

    # 2. Disabled user
    user = add_evals_user("banned@beta.gouv.fr", role="user")
    update_evals_user(user.email, is_active=False)
    record_login_event("banned@beta.gouv.fr")
    logs = list_recent_access_logs()
    assert len(logs) == 2
    assert logs[0].action == "access_denied_disabled_user"


def test_record_logout(in_memory_db) -> None:
    """Test recording logout action."""
    add_evals_user("agent@beta.gouv.fr", role="user")
    record_logout("agent@beta.gouv.fr")

    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "logout"
    assert logs[0].email == "agent@beta.gouv.fr"


def test_user_management_crud(in_memory_db) -> None:
    """Test user creation, update, and deletion."""
    # 1. Add user
    user = add_evals_user("alice@beta.gouv.fr", role="user")
    assert user.email == "alice@beta.gouv.fr"
    assert user.role == "user"
    assert user.is_active is True

    # 2. Duplicate rejection
    with pytest.raises(ValueError, match="existe déjà"):
        add_evals_user("alice@beta.gouv.fr", role="user")

    # 3. Invalid role rejection
    with pytest.raises(ValueError, match="Rôle invalide"):
        add_evals_user("bob@beta.gouv.fr", role="superuser")

    # 4. Update role and status
    updated = update_evals_user("alice@beta.gouv.fr", role="admin", is_active=False)
    assert updated.role == "admin"
    assert updated.is_active is False

    # 5. List users
    users = list_evals_users()
    assert len(users) == 1

    # 6. Delete user
    assert delete_evals_user("alice@beta.gouv.fr") is True
    assert len(list_evals_users()) == 0


def test_patch_streamlit_oidc_prompt() -> None:
    """Test that patch_streamlit_oidc_prompt removes prompt parameter from client_kwargs."""
    patch_streamlit_oidc_prompt()

    import streamlit.web.server.oauth_authlib_routes as routes

    client, _ = routes.create_oauth_client("proconnect")
    assert "prompt" not in client.client_kwargs


def test_verify_user_access_initial_admins_auto_provisioning(in_memory_db) -> None:
    """Test that initial administrators are automatically provisioned as ADMIN on first login."""
    # Ensure neither account exists initially
    assert len(list_evals_users()) == 0

    # First login with nicolas.sagon@ext.beta.gouv.fr
    is_allowed, user, reason = verify_user_access("nicolas.sagon@ext.beta.gouv.fr")
    assert is_allowed is True
    assert user is not None
    assert user.email == "nicolas.sagon@ext.beta.gouv.fr"
    assert user.role == UserRole.ADMIN.value
    assert user.is_active is True

    # User is now persisted in the database
    users = list_evals_users()
    assert len(users) == 1
    assert users[0].email == "nicolas.sagon@ext.beta.gouv.fr"
    assert users[0].role == UserRole.ADMIN.value


def test_fetch_proconnect_userinfo_json() -> None:
    """Test fetching and parsing JSON userinfo claims."""
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_client.load_server_metadata.return_value = {
        "userinfo_endpoint": "https://fca.integ01.dev-agentconnect.fr/api/v2/userinfo"
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sub": "user-sub-123",
        "email": "nicolas.sagon@ext.beta.gouv.fr",
        "given_name": "Nicolas",
        "usual_name": "Sagon",
    }
    mock_client.get.return_value = mock_resp

    token = {"access_token": "valid_token"}
    claims = fetch_proconnect_userinfo(mock_client, token)

    assert claims["email"] == "nicolas.sagon@ext.beta.gouv.fr"
    assert claims["given_name"] == "Nicolas"
    assert claims["usual_name"] == "Sagon"
    assert claims["name"] == "Nicolas Sagon"


def test_fetch_proconnect_userinfo_jwt() -> None:
    """Test fetching and decoding signed JWT userinfo claims."""
    import base64
    import json
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_client.load_server_metadata.return_value = {
        "userinfo_endpoint": "https://fca.integ01.dev-agentconnect.fr/api/v2/userinfo"
    }

    raw_payload = {
        "sub": "user-sub-456",
        "email": "agent@education.gouv.fr",
        "given_name": "Camille",
        "family_name": "Dupont",
    }
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps(raw_payload).encode()).decode().rstrip("=")
    )
    jwt_string = f"{header}.{payload}.mocksignature"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = Exception("Not valid JSON")
    mock_resp.text = jwt_string
    mock_client.get.return_value = mock_resp

    token = {"access_token": "valid_token"}
    claims = fetch_proconnect_userinfo(mock_client, token)

    assert claims["email"] == "agent@education.gouv.fr"
    assert claims["given_name"] == "Camille"
    assert claims["name"] == "Camille Dupont"


def test_patched_authorize_access_token_enriches_userinfo() -> None:
    """Test that TornadoOAuth2App.authorize_access_token enriches userinfo with userinfo_endpoint claims."""
    from unittest.mock import MagicMock, patch
    from streamlit.web.server.oidc_mixin import TornadoOAuth

    patch_streamlit_oidc()

    oauth = TornadoOAuth({
        "proconnect": {
            "client_id": "test",
            "client_secret": "test",
            "server_metadata_url": "https://fca.integ01.dev-agentconnect.fr/api/v2/.well-known/openid-configuration",
        }
    })
    oauth.register("proconnect")
    client = oauth.create_client("proconnect")

    fake_handler = MagicMock()
    fake_handler.get_argument.side_effect = lambda arg, default=None: {
        "code": "test_code",
        "state": "test_state",
    }.get(arg, default)

    # Mock internal methods of TornadoOAuth2App
    with patch.object(client.framework, "get_state_data", return_value={"nonce": "test_nonce"}), \
         patch.object(client.framework, "clear_state_data"), \
         patch.object(client, "fetch_access_token", return_value={"access_token": "tok123", "id_token": "id123"}), \
         patch.object(client, "parse_id_token", return_value={"sub": "sub123"}), \
         patch("document_ia_evals.utils.auth_secrets.fetch_proconnect_userinfo") as mock_fetch, \
         patch("document_ia_evals.services.auth_service.record_login_event") as mock_login_event:

        mock_fetch.return_value = {
            "email": "nicolas.sagon@ext.beta.gouv.fr",
            "given_name": "Nicolas",
            "usual_name": "Sagon",
            "name": "Nicolas Sagon",
        }

        token = client.authorize_access_token(fake_handler)
        assert "userinfo" in token
        assert token["userinfo"]["email"] == "nicolas.sagon@ext.beta.gouv.fr"
        assert token["userinfo"]["name"] == "Nicolas Sagon"
        assert token["userinfo"]["sub"] == "sub123"
        mock_login_event.assert_called_once()
        assert mock_login_event.call_args[0][0] == "nicolas.sagon@ext.beta.gouv.fr"
