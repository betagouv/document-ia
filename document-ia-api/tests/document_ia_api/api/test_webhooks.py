"""
Integration tests for admin webhooks endpoints.

We mock the repository via patching the service's repository dependency, mirroring the
pattern used by organization tests. These tests exercise:
- GET /api/v1/admin/organizations/{organization_id}/webhooks
- POST /api/v1/admin/organizations/{organization_id}/webhooks
- DELETE /api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO


class TestListWebhooks:
    def test_list_webhooks_success(self, client_with_api_key_admin, admin_api_key_value, organization_id):
        now = datetime.now(timezone.utc)
        mock_webhooks = [
            WebHookDTO(
                id=uuid4(),
                organization_id=organization_id,
                url="https://example.com/webhook/a",
                headers={"X-Signature": "abc123"},
                created_at=now,
                updated_at=now,
            ),
            WebHookDTO(
                id=uuid4(),
                organization_id=organization_id,
                url="https://example.com/webhook/b",
                headers={"X-Auth": "token"},
                created_at=now,
                updated_at=now,
            ),
        ]

        with patch(
            "document_ia_api.application.services.webhook.webhook_service.WebHookRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.list_webhooks_by_organization = AsyncMock(return_value=mock_webhooks)

            resp = client_with_api_key_admin.get(
                f"/api/v1/admin/organizations/{organization_id}/webhooks",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list) and len(data) == 2
            assert data[0]["url"].endswith("/a")
            assert data[1]["headers"] == {"X-Auth": "token"}

    def test_list_webhooks_unauthorized(self, client_without_api_key, organization_id):
        resp = client_without_api_key.get(
            f"/api/v1/admin/organizations/{organization_id}/webhooks"
        )
        assert resp.status_code == 403


class TestCreateWebhook:
    def test_create_webhook_success(self, client_with_api_key_admin, admin_api_key_value, organization_id):
        now = datetime.now(timezone.utc)
        new_id = uuid4()
        mock_dto = WebHookDTO(
            id=new_id,
            organization_id=organization_id,
            url="https://example.com/webhook/a",
            headers={"X-Signature": "abc123"},
            created_at=now,
            updated_at=now,
        )

        payload = {
            "url": "https://example.com/webhook/a",
            "headers": {"X-Signature": "abc123"},
        }

        with patch(
            "document_ia_api.application.services.webhook.webhook_service.WebHookRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.create = AsyncMock(return_value=mock_dto)

            resp = client_with_api_key_admin.post(
                f"/api/v1/admin/organizations/{organization_id}/webhooks",
                json=payload,
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert resp.status_code == 201
            data = resp.json()
            assert data["id"] == str(new_id)
            assert data["url"] == payload["url"]
            assert data["headers"] == payload["headers"]

    def test_create_webhook_validation_error(self, client_with_api_key_admin, admin_api_key_value, organization_id):
        # Missing required 'url'
        payload = {"headers": {"X": "Y"}}
        resp = client_with_api_key_admin.post(
            f"/api/v1/admin/organizations/{organization_id}/webhooks",
            json=payload,
            headers={"X-API-KEY": admin_api_key_value},
        )
        assert resp.status_code == 422


class TestDeleteWebhook:
    def test_delete_webhook_success(self, client_with_api_key_admin, admin_api_key_value, organization_id):
        webhook_id = uuid4()

        with patch(
            "document_ia_api.application.services.webhook.webhook_service.WebHookRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.delete = AsyncMock(return_value=True)

            resp = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert resp.status_code == 204
            assert resp.text == ""

    def test_delete_webhook_not_found(self, client_with_api_key_admin, admin_api_key_value, organization_id):
        webhook_id = uuid4()

        with patch(
            "document_ia_api.application.services.webhook.webhook_service.WebHookRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.delete = AsyncMock(return_value=False)

            resp = client_with_api_key_admin.delete(
                f"/api/v1/admin/organizations/{organization_id}/webhooks/{webhook_id}",
                headers={"X-API-KEY": admin_api_key_value},
            )

            assert resp.status_code == 404
            data = resp.json()
            assert data["status"] == 404
