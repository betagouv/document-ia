import uuid

import pytest

from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.repository.organization_repository import OrganizationRepository
from document_ia_infra.data.webhook.repository.webhook_repository import WebHookRepository


@pytest.mark.asyncio
class TestWebHookRepository:
    async def test_create_list_delete_webhook(self, isolated_database_manager):
        # Create an organization to attach webhooks to
        async with isolated_database_manager.local_session() as session:
            org_repo = OrganizationRepository(session)
            webhook_repo = WebHookRepository(session)
            created_webhook_id = None
            created_org_id = None
            try:
                org = await org_repo.create(
                    contact_email=f"org-{uuid.uuid4().hex[:8]}@example.com",
                    name=f"Org {uuid.uuid4().hex[:6]}",
                    platform_role=PlatformRole.STANDARD,
                )
                await session.commit()
                created_org_id = org.id

                # Create a webhook
                dto = await webhook_repo.create(
                    organization_id=created_org_id,
                    url="https://example.com/webhook",
                    headers={"X-Signature": "abc123", "X-Env": "test"},
                )
                await session.commit()
                created_webhook_id = dto.id

                assert str(dto.organization_id) == str(created_org_id)
                assert dto.url == "https://example.com/webhook"
                assert dto.headers.get("X-Signature") == "abc123"

                # List webhooks for this organization
                items = await webhook_repo.list_webhooks_by_organization(created_org_id)
                assert isinstance(items, list)
                assert any(x.id == created_webhook_id for x in items)

                # Delete the webhook
                deleted = await webhook_repo.delete(created_webhook_id)
                await session.commit()
                assert deleted is True

                # Verify list is now empty
                items_after = await webhook_repo.list_webhooks_by_organization(created_org_id)
                assert all(x.id != created_webhook_id for x in items_after)
            finally:
                # Cleanup organization best-effort in fresh session
                if created_org_id is not None:
                    async with isolated_database_manager.local_session() as clean_session:
                        clean_org_repo = OrganizationRepository(clean_session)
                        try:
                            await clean_org_repo.delete(created_org_id)
                            await clean_session.commit()
                        except Exception:
                            await clean_session.rollback()

    async def test_delete_nonexistent_returns_false(self, isolated_database_manager):
        # Ensure delete returns False when webhook does not exist
        async with isolated_database_manager.local_session() as session:
            repo = WebHookRepository(session)
            result = await repo.delete(uuid.uuid4())
            assert result is False
