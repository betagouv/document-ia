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
    record_logout,
    update_evals_user,
    verify_user_access,
)
from document_ia_evals.utils.auth_secrets import generate_secrets_toml


@pytest.fixture
def in_memory_db():
    """Create an isolated in-memory SQLite database for authentication testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[EvalsUser.__table__, EvalsAccessLog.__table__],
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
    """Test access verification for an unregistered user."""
    is_allowed, user, reason = verify_user_access("unknown@beta.gouv.fr")

    assert not is_allowed
    assert user is None
    assert "Accès refusé" in reason

    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "access_denied_unknown_user"
    assert logs[0].email == "unknown@beta.gouv.fr"


def test_verify_user_access_disabled_user(in_memory_db) -> None:
    """Test access verification for a deactivated user."""
    user = add_evals_user("inactive@beta.gouv.fr", role="user")
    update_evals_user(user.email, is_active=False)

    is_allowed, verified_user, reason = verify_user_access("inactive@beta.gouv.fr")

    assert not is_allowed
    assert verified_user is None
    assert "désactivé" in reason

    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "access_denied_disabled_user"


def test_verify_user_access_success(in_memory_db) -> None:
    """Test successful user login."""
    add_evals_user("nicolas.sagon@beta.gouv.fr", role="admin")

    is_allowed, user, reason = verify_user_access("nicolas.sagon@beta.gouv.fr")

    assert is_allowed
    assert user is not None
    assert user.email == "nicolas.sagon@beta.gouv.fr"
    assert user.role == UserRole.ADMIN.value
    assert user.last_login_at is not None

    logs = list_recent_access_logs()
    assert len(logs) == 1
    assert logs[0].action == "login_success"


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
