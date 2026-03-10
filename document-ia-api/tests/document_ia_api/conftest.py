"""
Pytest configuration and fixtures for Document IA API tests.

This module provides common fixtures and configuration for all integration tests.
"""

import os
# Add the src directory to Python path for imports
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import SecretStr

import document_ia_infra.data.database as db_module
from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.organization.repository.organization_repository import OrganizationRepository

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
def mock_api_key_service_auth(monkeypatch, standard_api_key_value, admin_api_key_value, invalid_api_key_value, organization_id):
    """Mock ApiKeyService.get_from_presented_key pour retourner des ApiKeyDTO selon la clé,
    avec un OrganizationDTO dont l'id correspond à l'organisation réellement créée en DB.

    - standard_api_key_value => organization rôle STANDARD (id = organization_id)
    - admin_api_key_value => organization rôle PLATFORM_ADMIN (id = organization_id)
    - invalid_api_key_value => None (simule clé invalide)
    - toute autre clé => organization STANDARD (fallback, id = organization_id)
    """
    from document_ia_api.api import auth as auth_mod

    now = datetime.now(timezone.utc)

    org_standard = OrganizationDTO(
        id=organization_id,
        contact_email="standard@example.org",
        name="Standard Org",
        platform_role=PlatformRole.STANDARD,
        created_at=now,
        updated_at=now,
    )
    org_admin = OrganizationDTO(
        id=organization_id,
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


@pytest.fixture(autouse=True)
async def isolated_database_manager(request):
    """Fournit un DatabaseManager neuf par test et remplace l’instance globale.

    - Crée un nouvel async_engine/async_sessionmaker par test (évite de réutiliser
      un pool attaché à une event loop précédente).
    - Remplace db_module.database_manager et, si présent, la variable
      `database_manager` du module de test.
    - Dispose proprement l’engine en fin de test.
    """
    manager = DatabaseManager()

    # Remplace l’instance globale du module source
    db_module.database_manager = manager

    # Si le module de test a son propre symbole `database_manager` (import direct),
    # on le remplace aussi pour que les fonctions utilisent le nouveau manager.
    test_mod = getattr(request.node, "module", None)
    if test_mod is not None and hasattr(test_mod, "database_manager"):
        setattr(test_mod, "database_manager", manager)

    try:
        yield manager
    finally:
        # Ferme proprement l’engine/pool pour éviter les handles ouverts
        try:
            await manager.async_engine.dispose()
        except Exception:
            pass


@pytest.fixture
async def organization_id(isolated_database_manager):
    """Crée une organisation pour un test et retourne son UUID.

    Nettoyage automatique après le test (delete + commit).
    """
    async with isolated_database_manager.local_session() as session:
        repo = OrganizationRepository(session)
        org = await repo.create(
            contact_email=f"org-{uuid4().hex[:8]}@example.com",
            name=f"Org {uuid4().hex[:6]}",
            platform_role=PlatformRole.STANDARD,
        )
        await session.commit()
        created_id = org.id

    # Fournit l'identifiant au test
    yield created_id

    # Cleanup
    async with isolated_database_manager.local_session() as session:
        repo = OrganizationRepository(session)
        try:
            await repo.delete(created_id)
            await session.commit()
        except Exception:
            await session.rollback()
