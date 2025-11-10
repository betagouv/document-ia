import pytest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from starlette.requests import Request

from document_ia_api.api.auth import (
    verify_api_key,
    get_api_key,
    get_current_organization,
    is_platform_admin,
)
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


@pytest.fixture()
def org_admin() -> OrganizationDTO:
    return OrganizationDTO(
        id=uuid4(),
        contact_email="admin@example.org",
        name="Admin Org",
        platform_role=PlatformRole.PLATFORM_ADMIN,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def org_standard() -> OrganizationDTO:
    return OrganizationDTO(
        id=uuid4(),
        contact_email="user@example.org",
        name="User Org",
        platform_role=PlatformRole.STANDARD,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def api_key_with_org(org_admin: OrganizationDTO) -> ApiKeyDTO:
    now = datetime.now(timezone.utc)
    return ApiKeyDTO(
        id=uuid4(),
        organization_id=org_admin.id,
        organization=org_admin,
        key_hash="argon2$hash",
        prefix="ABCD1234",
        status=ApiKeyStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def api_key_without_org(org_admin: OrganizationDTO) -> ApiKeyDTO:
    now = datetime.now(timezone.utc)
    return ApiKeyDTO(
        id=uuid4(),
        organization_id=uuid4(),
        organization=None,
        key_hash="argon2$hash",
        prefix="WXYZ5678",
        status=ApiKeyStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


class _DummyService:
    def __init__(self, _):
        self._value = None

    def set_value(self, v):
        self._value = v

    async def get_from_presented_key(self, _presented: str):
        return self._value


@pytest.fixture()
def make_service(monkeypatch):
    # Monkeypatch ApiKeyService in auth module to our dummy
    from document_ia_api.api import auth as auth_mod

    dummy = _DummyService(None)

    def _factory(_db_session):
        return dummy

    monkeypatch.setattr(auth_mod, "ApiKeyService", _factory)
    return dummy


@pytest.mark.asyncio
async def test_verify_api_key_success_sets_state_and_returns_dto(make_service, api_key_with_org):
    make_service.set_value(api_key_with_org)
    request = Request(scope={"type": "http"})

    result = await verify_api_key(request, api_key="presented-key", db_session=object())

    assert isinstance(result, ApiKeyDTO)
    assert getattr(request.state, "organization", None) is api_key_with_org.organization


@pytest.mark.asyncio
async def test_verify_api_key_invalid_key_raises_401(make_service):
    make_service.set_value(None)
    request = Request(scope={"type": "http"})

    with pytest.raises(HTTPException) as exc:
        await verify_api_key(request, api_key="bad-key", db_session=object())
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid API key"


@pytest.mark.asyncio
async def test_verify_api_key_without_organization_raises_401(make_service, api_key_without_org):
    make_service.set_value(api_key_without_org)
    request = Request(scope={"type": "http"})

    with pytest.raises(HTTPException) as exc:
        await verify_api_key(request, api_key="presented-key", db_session=object())
    assert exc.value.status_code == 401
    assert exc.value.detail == "API key has no associated organization"


def test_get_api_key_returns_header_value():
    assert get_api_key("the-key") == "the-key"
    assert get_api_key(None) is None


def test_get_current_organization_success(org_standard):
    request = Request(scope={"type": "http"})
    request.state.organization = org_standard
    assert get_current_organization(request) is org_standard


def test_get_current_organization_missing_raises_401():
    request = Request(scope={"type": "http"})
    with pytest.raises(HTTPException) as exc:
        get_current_organization(request)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized access: No organization found"


@pytest.mark.asyncio
async def test_is_platform_admin_allows_admin(org_admin):
    # We can pass any ApiKeyDTO instance for the first param, it's not used in logic here
    dummy_api_key = object()
    assert is_platform_admin(dummy_api_key, org_admin) is None


@pytest.mark.asyncio
async def test_is_platform_admin_denies_non_admin(org_standard):
    dummy_api_key = object()
    with pytest.raises(HTTPException) as exc:
        is_platform_admin(dummy_api_key, org_standard)
    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized access: Platform admin required"
