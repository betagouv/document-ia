"""
Integration tests for API key admin endpoints.

Tests all endpoints with database layer mocked to avoid event loop conflicts.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


class TestCreateAPIKey:
    """Test POST /api/v1/admin/organizations/{organization_id}/api-keys endpoint."""

    def test_create_api_key_success(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful creation of API key."""
        org_id = uuid4()
        now = datetime.now(timezone.utc)

        mock_org = OrganizationDTO(
            id=org_id,
            name="Test Org",
            contact_email="test@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        api_key_id = uuid4()
        mock_api_key = ApiKeyDTO(
            id=api_key_id,
            organization_id=org_id,
            organization=mock_org,
            key_hash="argon2$dummy_hash",
            prefix="TESTKEY1",
            status=ApiKeyStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.create = AsyncMock(return_value=mock_api_key)

            with patch("document_ia_api.application.services.api_key.api_key_helper.ApiKeyHelper") as mock_helper_class:
                mock_helper = mock_helper_class.return_value
                mock_helper.generate_new_api_key.return_value = (
                    "dia_dev_v1_TESTKEY1_ABCDEFGHIJKLMNOPQRSTUVWX1234567890YZ12_IFZS",
                    "TESTKEY1",
                    "IFZS",
                    "argon2$dummy_hash"
                )

                response = client_with_api_key_admin.post(
                    f"/api/v1/admin/organizations/{org_id}/api-keys",
                    headers={"X-API-KEY": admin_api_key_value},
                )

                assert response.status_code == 201
                data = response.json()
                assert "id" in data
                assert "key" in data
                assert data["prefix"] == "TESTKEY1"
                assert data["status"] == "Active"
                assert "created_at" in data
                assert "updated_at" in data
                assert data["key"].startswith("dia_dev_1_")

    def test_create_api_key_organization_not_found(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 404 when organization does not exist."""
        fake_org_id = "00000000-0000-0000-0000-000000000000"

        from sqlalchemy.exc import IntegrityError

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.create = AsyncMock(side_effect=IntegrityError("", "", ""))

            with patch("document_ia_api.application.services.api_key.api_key_helper.ApiKeyHelper") as mock_helper_class:
                mock_helper = mock_helper_class.return_value
                mock_helper.generate_new_api_key.return_value = (
                    "dia_dev_v1_TESTKEY1_ABCDEFGHIJKLMNOPQRSTUVWX1234567890YZ12_IFZS",
                    "TESTKEY1",
                    "IFZS",
                    "argon2$dummy_hash"
                )

                response = client_with_api_key_admin.post(
                    f"/api/v1/admin/organizations/{fake_org_id}/api-keys",
                    headers={"X-API-KEY": admin_api_key_value},
                )

                assert response.status_code == 404
                data = response.json()
                assert data["status"] == 404

    def test_create_api_key_invalid_uuid(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when organization_id is not a valid UUID."""
        response = client_with_api_key_admin.post(
            "/api/v1/admin/organizations/not-a-uuid/api-keys",
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_create_api_key_unauthorized(self, client_without_api_key):
        """Test 403 when no API key is provided."""
        org_id = uuid4()
        response = client_without_api_key.post(
            f"/api/v1/admin/organizations/{org_id}/api-keys"
        )

        assert response.status_code == 403

    def test_create_api_key_forbidden_standard_user(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 401 when standard user tries to create API key."""
        org_id = uuid4()
        response = client_with_api_key_standard.post(
            f"/api/v1/admin/organizations/{org_id}/api-keys",
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401


class TestUpdateAPIKeyStatus:
    """Test PUT /api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id}/status endpoint."""

    def test_update_api_key_status_success(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful update of API key status."""
        org_id = uuid4()
        api_key_id = uuid4()
        now = datetime.now(timezone.utc)

        mock_org = OrganizationDTO(
            id=org_id,
            name="Test Org",
            contact_email="test@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        mock_api_key = ApiKeyDTO(
            id=api_key_id,
            organization_id=org_id,
            organization=mock_org,
            key_hash="argon2$dummy_hash",
            prefix="TESTKEY1",
            status=ApiKeyStatus.REVOKED,
            created_at=now,
            updated_at=now,
        )

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.update_status_by_id = AsyncMock(return_value=mock_api_key)

            payload = {"status": "Revoked"}
            response = client_with_api_key_admin.put(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == str(api_key_id)
            assert data["status"] == "Revoked"

    def test_update_api_key_status_to_active(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test update API key status to Active."""
        org_id = uuid4()
        api_key_id = uuid4()
        now = datetime.now(timezone.utc)

        mock_org = OrganizationDTO(
            id=org_id,
            name="Test Org",
            contact_email="test@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        mock_api_key = ApiKeyDTO(
            id=api_key_id,
            organization_id=org_id,
            organization=mock_org,
            key_hash="argon2$dummy_hash",
            prefix="TESTKEY1",
            status=ApiKeyStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.update_status_by_id = AsyncMock(return_value=mock_api_key)

            payload = {"status": "Active"}
            response = client_with_api_key_admin.put(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "Active"

    def test_update_api_key_status_to_expired(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test update API key status to Expired."""
        org_id = uuid4()
        api_key_id = uuid4()
        now = datetime.now(timezone.utc)

        mock_org = OrganizationDTO(
            id=org_id,
            name="Test Org",
            contact_email="test@example.com",
            platform_role=PlatformRole.STANDARD,
            created_at=now,
            updated_at=now,
        )

        mock_api_key = ApiKeyDTO(
            id=api_key_id,
            organization_id=org_id,
            organization=mock_org,
            key_hash="argon2$dummy_hash",
            prefix="TESTKEY1",
            status=ApiKeyStatus.EXPIRED,
            created_at=now,
            updated_at=now,
        )

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.update_status_by_id = AsyncMock(return_value=mock_api_key)

            payload = {"status": "Expired"}
            response = client_with_api_key_admin.put(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "Expired"

    def test_update_api_key_status_not_found(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 404 when API key does not exist."""
        org_id = uuid4()
        fake_api_key_id = "00000000-0000-0000-0000-000000000000"

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.update_status_by_id = AsyncMock(return_value=None)

            payload = {"status": "Revoked"}
            response = client_with_api_key_admin.put(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{fake_api_key_id}/status",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == 404

    def test_update_api_key_status_invalid_status(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when status is invalid."""
        org_id = uuid4()
        api_key_id = uuid4()

        payload = {"status": "InvalidStatus"}
        response = client_with_api_key_admin.put(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_update_api_key_status_missing_status(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when status field is missing."""
        org_id = uuid4()
        api_key_id = uuid4()

        payload = {}
        response = client_with_api_key_admin.put(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_update_api_key_status_invalid_org_uuid(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when organization_id is not a valid UUID."""
        api_key_id = uuid4()

        payload = {"status": "Revoked"}
        response = client_with_api_key_admin.put(
            f"/api/v1/admin/organizations/not-a-uuid/api-keys/{api_key_id}/status",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_update_api_key_status_invalid_api_key_uuid(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when api_key_id is not a valid UUID."""
        org_id = uuid4()

        payload = {"status": "Revoked"}
        response = client_with_api_key_admin.put(
            f"/api/v1/admin/organizations/{org_id}/api-keys/not-a-uuid/status",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_update_api_key_status_unauthorized(self, client_without_api_key):
        """Test 403 when no API key is provided."""
        org_id = uuid4()
        api_key_id = uuid4()

        payload = {"status": "Revoked"}
        response = client_without_api_key.put(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
            json=payload,
        )

        assert response.status_code == 403

    def test_update_api_key_status_forbidden_standard_user(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 401 when standard user tries to update API key status."""
        org_id = uuid4()
        api_key_id = uuid4()

        payload = {"status": "Revoked"}
        response = client_with_api_key_standard.put(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}/status",
            json=payload,
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401


class TestDeleteAPIKey:
    """Test DELETE /api/v1/admin/organizations/{organization_id}/api-keys/{api_key_id} endpoint."""

    def test_delete_api_key_success(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test successful deletion of API key."""
        org_id = uuid4()
        api_key_id = uuid4()

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.delete = AsyncMock(return_value=True)

            response = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 204
            assert response.content == b""

    def test_delete_api_key_not_found(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 404 when API key does not exist."""
        org_id = uuid4()
        fake_api_key_id = "00000000-0000-0000-0000-000000000000"

        with patch("document_ia_api.application.services.api_key.api_key_service.ApiKeyRepository") as mock_repo_class:
            mock_repo = mock_repo_class.return_value
            mock_repo.delete = AsyncMock(return_value=False)

            response = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{org_id}/api-keys/{fake_api_key_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == 404

    def test_delete_api_key_invalid_org_uuid(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when organization_id is not a valid UUID."""
        api_key_id = uuid4()

        response = client_with_api_key_admin.delete(
            f"/api/v1/admin/organizations/not-a-uuid/api-keys/{api_key_id}",
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_delete_api_key_invalid_api_key_uuid(
        self, client_with_api_key_admin, admin_api_key_value
    ):
        """Test 422 when api_key_id is not a valid UUID."""
        org_id = uuid4()

        response = client_with_api_key_admin.delete(
            f"/api/v1/admin/organizations/{org_id}/api-keys/not-a-uuid",
            headers={"X-API-KEY": admin_api_key_value},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == 422
        assert data["code"] == "validation.failed"

    def test_delete_api_key_unauthorized(self, client_without_api_key):
        """Test 403 when no API key is provided."""
        org_id = uuid4()
        api_key_id = uuid4()

        response = client_without_api_key.delete(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}"
        )

        assert response.status_code == 403

    def test_delete_api_key_forbidden_standard_user(
        self, client_with_api_key_standard, standard_api_key_value
    ):
        """Test 401 when standard user tries to delete API key."""
        org_id = uuid4()
        api_key_id = uuid4()

        response = client_with_api_key_standard.delete(
            f"/api/v1/admin/organizations/{org_id}/api-keys/{api_key_id}",
            headers={"X-API-KEY": standard_api_key_value},
        )

        assert response.status_code == 401
