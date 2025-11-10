"""
Pytest configuration and fixtures for Document IA API tests.

This module provides common fixtures and configuration for all integration tests.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv

# Add the src directory to Python path for imports
import sys

from pydantic import SecretStr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from document_ia_api.api.middleware.rate_limiting_middleware import RateLimitMiddleware
from document_ia_api.api.routes import router
from document_ia_api.schemas.rate_limiting import RateLimitInfo
from document_ia_api.api.exceptions.handler.exception_handlers import setup_exception_handlers
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus

# Load test environment variables
test_env_path = os.path.join(os.path.dirname(__file__), ".env.test")
if os.path.exists(test_env_path):
    load_dotenv(test_env_path)


def create_test_app(api_key: str = None):
    """
    Create a FastAPI test application with controlled settings.
    """

    class TestSettings:
        APP_VERSION = "1.0.0-test"
        API_KEY = SecretStr(api_key) if api_key else None

    app = FastAPI(title="API Document IA - Test")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RateLimitMiddleware)
    setup_exception_handlers(app)

    # Override legacy settings object if still referenced somewhere
    import document_ia_api.api.auth as auth_mod
    auth_mod.settings = TestSettings()

    app.include_router(router, prefix="/api", tags=["API"])
    return app


@pytest.fixture
def mock_redis_service():
    mock_service = MagicMock()
    mock_service.check_rate_limit = AsyncMock(
        return_value=(
            True,
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=99,
                remaining_daily=999,
                reset_minute="2024-01-01T12:01:00",
                reset_daily="2024-01-02T00:00:00",
            ),
        )
    )
    return mock_service

# ---------------------------------------------------------------------------
# API Key fixtures (values)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def standard_api_key_value() -> str:
    return "standard-test-api-key"


@pytest.fixture(scope="session")
def admin_api_key_value() -> str:
    return "admin-test-api-key"


@pytest.fixture(scope="session")
def invalid_api_key_value() -> str:
    return "invalid-test-api-key"

# ---------------------------------------------------------------------------
# Central auth monkeypatch: mock ApiKeyService.get_from_presented_key
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_api_key_service_auth(monkeypatch, standard_api_key_value, admin_api_key_value, invalid_api_key_value):
    """Mock ApiKeyService.get_from_presented_key pour retourner des ApiKeyDTO selon la clé.

    - standard_api_key_value => organization rôle STANDARD
    - admin_api_key_value => organization rôle PLATFORM_ADMIN
    - invalid_api_key_value => None (simule clé invalide)
    - toute autre clé => organization STANDARD (par défaut)
    """
    from document_ia_api.application.services.api_key import api_key_service as svc_mod
    from document_ia_api.api import auth as auth_mod

    now = datetime.now(timezone.utc)

    org_standard = OrganizationDTO(
        id=uuid4(),
        contact_email="standard@example.org",
        name="Standard Org",
        platform_role=PlatformRole.STANDARD,
        created_at=now,
        updated_at=now,
    )
    org_admin = OrganizationDTO(
        id=uuid4(),
        contact_email="admin@example.org",
        name="Admin Org",
        platform_role=PlatformRole.PLATFORM_ADMIN,
        created_at=now,
        updated_at=now,
    )

    def _make_api_key(org: OrganizationDTO, prefix: str) -> ApiKeyDTO:
        return ApiKeyDTO(
            id=uuid4(),
            organization_id=org.id,
            organization=org,
            key_hash="argon2$dummy_hash",  # not used in tests
            prefix=prefix[:8].ljust(8, "X"),
            status=ApiKeyStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    api_key_standard_dto = _make_api_key(org_standard, "STDKEY12")
    api_key_admin_dto = _make_api_key(org_admin, "ADMKEY12")

    async def fake_get_from_presented_key(self, presented: str):  # noqa: ARG001
        if presented == invalid_api_key_value or presented == "invalid-api-key":
            return None
        if presented == admin_api_key_value:
            return api_key_admin_dto
        if presented == standard_api_key_value:
            return api_key_standard_dto
        # default fallback: treat as standard
        return api_key_standard_dto

    # Patch sur la classe ApiKeyService importée dans auth (la source de vérité de verify_api_key)
    monkeypatch.setattr(
        auth_mod.ApiKeyService,
        "get_from_presented_key",
        fake_get_from_presented_key,
        raising=True,
    )

    yield  # Nothing to teardown

# ---------------------------------------------------------------------------
# Client factory util
# ---------------------------------------------------------------------------

def _build_client(mock_redis_service) -> TestClient:
    import document_ia_api.api.middleware.rate_limiting_middleware as rl_mod
    original = rl_mod.redis_service
    rl_mod.redis_service = mock_redis_service
    client = TestClient(create_test_app())

    def _finalizer():
        rl_mod.redis_service = original
    # register finalizer via yield pattern in calling fixture
    return client, _finalizer

# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_api_key_standard(mock_redis_service, standard_api_key_value):
    client, finalizer = _build_client(mock_redis_service)
    yield client
    finalizer()

@pytest.fixture
def client_with_api_key_admin(mock_redis_service, admin_api_key_value):
    client, finalizer = _build_client(mock_redis_service)
    yield client
    finalizer()

@pytest.fixture
def client_with_api_key_invalid(mock_redis_service, invalid_api_key_value):
    client, finalizer = _build_client(mock_redis_service)
    yield client
    finalizer()

@pytest.fixture
def client_without_api_key(mock_redis_service):
    client, finalizer = _build_client(mock_redis_service)
    yield client
    finalizer()
