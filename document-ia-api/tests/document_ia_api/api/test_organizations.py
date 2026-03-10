"""
Integration tests for organization admin endpoints.

Tests all endpoints with database layer mocked to avoid event loop conflicts.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


class TestGetOrganizationList:
    """Test GET /api/v1/admin/organizations endpoint."""

    def test_get_organizations_success(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful retrieval of organizations list."""
        # Mock organization repository
        now = datetime.now(timezone.utc)
        mock_orgs = [
            OrganizationDTO(
                id=uuid4(),
                name="Test Org 1",
                contact_email="test1@example.com",
                platform_role=PlatformRole.STANDARD,
                created_at=now,
                updated_at=now,
            ),
            OrganizationDTO(
                id=uuid4(),
                name="Test Org 2",
                contact_email="test2@example.com",
                platform_role=PlatformRole.PLATFORM_ADMIN,
                created_at=now,
                updated_at=now,
            ),
        ]

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.list = AsyncMock(return_value=mock_orgs)

            response = client_with_api_key_admin.get(
                "/api/v1/admin/organizations",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["name"] == "Test Org 1"
            assert data[0]["contact_email"] == "test1@example.com"
            assert data[0]["platform_role"] == "Standard"
            assert data[1]["name"] == "Test Org 2"
            assert data[1]["platform_role"] == "PlatformAdmin"

    def test_get_organizations_unauthorized_no_api_key(
            self, client_without_api_key
    ):
        """Test 401 when no API key is provided."""
        response = client_without_api_key.get("/api/v1/admin/organizations")

        assert response.status_code == 403

    def test_get_organizations_unauthorized_invalid_api_key(
            self, client_with_api_key_invalid, invalid_api_key_value
    ):
        """Test 401 when invalid API key is provided."""
        response = client_with_api_key_invalid.get(
            "/api/v1/admin/organizations",
            headers={"X-API-KEY": invalid_api_key_value},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == 401
        assert data["code"] == "http.unauthorized"

    def test_get_organizations_forbidden_standard_user(
            self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 403 when standard user (non-admin) tries to access."""
        response = client_with_api_key_standard.get(
            "/api/v1/admin/organizations",
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401
        data = response.json()
        assert "admin" in data["detail"].lower() or "unauthorized" in data["detail"].lower()


class TestGetOrganizationDetails:
    """Test GET /api/v1/admin/organizations/{organization_id} endpoint."""

    def test_get_organization_details_success(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful retrieval of organization details."""
        now = datetime.now(timezone.utc)
        org_id = uuid4()
        mock_org = OrganizationDTO(
            id=org_id,
            name="Test Org Details",
            contact_email="details@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
            api_keys=[],
        )

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.get_with_api_keys = AsyncMock(return_value=mock_org)

            response = client_with_api_key_admin.get(
                f"/api/v1/admin/organizations/{org_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == str(org_id)
            assert data["name"] == "Test Org Details"
            assert data["contact_email"] == "details@example.com"
            assert data["platform_role"] == "Standard"
            assert "api_keys" in data
            assert isinstance(data["api_keys"], list)

    def test_get_organization_details_not_found(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 404 when organization does not exist."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.get_with_api_keys = AsyncMock(return_value=None)

            response = client_with_api_key_admin.get(
                f"/api/v1/admin/organizations/{fake_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == 404

    def test_get_organization_details_invalid_uuid(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when organization_id is not a valid UUID."""
        response = client_with_api_key_admin.get(
            "/api/v1/admin/organizations/not-a-uuid",
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_get_organization_details_unauthorized(
            self, client_without_api_key
    ):
        """Test 401 when no API key is provided."""
        fake_id = uuid4()
        response = client_without_api_key.get(
            f"/api/v1/admin/organizations/{fake_id}"
        )

        assert response.status_code == 403

    def test_get_organization_details_forbidden_standard_user(
            self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 403 when standard user tries to access."""
        fake_id = uuid4()
        response = client_with_api_key_standard.get(
            f"/api/v1/admin/organizations/{fake_id}",
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401


class TestCreateOrganization:
    """Test POST /api/v1/admin/organizations endpoint."""

    def test_create_organization_success_standard(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful creation of standard organization."""
        payload = {
            "name": "New Org Standard",
            "contact_email": "neworg@example.com",
            "platform_role": "Standard",
        }

        now = datetime.now(timezone.utc)
        org_id = uuid4()
        mock_org = OrganizationDTO(
            id=org_id,
            name="New Org Standard",
            contact_email="neworg@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.create = AsyncMock(return_value=mock_org)

            # Mock db_session.commit()
            with patch(
                    "document_ia_api.application.services.organization.organization_service.AsyncSession"):
                response = client_with_api_key_admin.post(
                    "/api/v1/admin/organizations",
                    json=payload,
                    headers={"X-API-KEY": admin_api_key_value},
                )

                assert response.status_code == 201
                data = response.json()
                assert data["name"] == "New Org Standard"
                assert data["contact_email"] == "neworg@example.com"
                assert data["platform_role"] == "Standard"
                assert "id" in data
                assert "created_at" in data
                assert "updated_at" in data

    def test_create_organization_success_admin(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful creation of admin organization."""
        payload = {
            "name": "New Org Admin",
            "contact_email": "admin@example.com",
            "platform_role": "PlatformAdmin",
        }

        now = datetime.now(timezone.utc)
        org_id = uuid4()
        mock_org = OrganizationDTO(
            id=org_id,
            name="New Org Admin",
            contact_email="admin@example.com",
            platform_role=PlatformRole.PLATFORM_ADMIN,
            created_at=now,
            updated_at=now,
        )

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.create = AsyncMock(return_value=mock_org)

            response = client_with_api_key_admin.post(
                "/api/v1/admin/organizations",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["platform_role"] == "PlatformAdmin"

    def test_create_organization_success_default_role(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful creation with default role (Standard)."""
        payload = {
            "name": "Org Default Role",
            "contact_email": "default@example.com",
        }

        now = datetime.now(timezone.utc)
        org_id = uuid4()
        mock_org = OrganizationDTO(
            id=org_id,
            name="Org Default Role",
            contact_email="default@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.create = AsyncMock(return_value=mock_org)

            response = client_with_api_key_admin.post(
                "/api/v1/admin/organizations",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["platform_role"] == "Standard"

    def test_create_organization_validation_missing_name(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when name is missing."""
        payload = {
            "contact_email": "missing@example.com",
        }

        response = client_with_api_key_admin.post(
            "/api/v1/admin/organizations",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"
        assert "name" in str(data["errors"]).lower()

    def test_create_organization_validation_missing_email(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when contact_email is missing."""
        payload = {
            "name": "Missing Email Org",
        }

        response = client_with_api_key_admin.post(
            "/api/v1/admin/organizations",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert "contact_email" in str(data["errors"]).lower()

    def test_create_organization_validation_empty_body(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when body is empty."""
        response = client_with_api_key_admin.post(
            "/api/v1/admin/organizations",
            json={},
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_create_organization_validation_invalid_role(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when platform_role is invalid."""
        payload = {
            "name": "Invalid Role Org",
            "contact_email": "invalid@example.com",
            "platform_role": "InvalidRole",
        }

        response = client_with_api_key_admin.post(
            "/api/v1/admin/organizations",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422

    def test_create_organization_unauthorized(
            self, client_without_api_key
    ):
        """Test 401 when no API key is provided."""
        payload = {
            "name": "Unauthorized Org",
            "contact_email": "unauth@example.com",
        }

        response = client_without_api_key.post(
            "/api/v1/admin/organizations",
            json=payload,
        )

        assert response.status_code == 403

    def test_create_organization_forbidden_standard_user(
            self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 403 when standard user tries to create."""
        payload = {
            "name": "Forbidden Org",
            "contact_email": "forbidden@example.com",
        }

        response = client_with_api_key_standard.post(
            "/api/v1/admin/organizations",
            json=payload,
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401


class TestDeleteOrganization:
    """Test DELETE /api/v1/admin/organizations/{organization_id} endpoint."""

    def test_delete_organization_success(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful deletion of organization."""
        org_id = uuid4()

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.delete = AsyncMock(return_value=True)

            response = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{org_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 204
            assert response.content == b""

    def test_delete_organization_not_found(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 404 when trying to delete non-existent organization."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        with patch(
                "document_ia_api.application.services.organization.organization_service.OrganizationRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.delete = AsyncMock(return_value=False)

            response = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{fake_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == 404

    def test_delete_organization_invalid_uuid(
            self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when organization_id is not a valid UUID."""
        response = client_with_api_key_admin.delete(
            "/api/v1/admin/organizations/not-a-uuid",
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_delete_organization_unauthorized(
            self, client_without_api_key
    ):
        """Test 401 when no API key is provided."""
        fake_id = uuid4()
        response = client_without_api_key.delete(
            f"/api/v1/admin/organizations/{fake_id}"
        )

        assert response.status_code == 403

    def test_delete_organization_forbidden_standard_user(
            self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 403 when standard user tries to delete."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = client_with_api_key_standard.delete(
            f"/api/v1/admin/organizations/{fake_id}",
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401
