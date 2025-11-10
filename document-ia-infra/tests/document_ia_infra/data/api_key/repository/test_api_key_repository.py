import uuid

import pytest

from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.api_key.repository.api_key import ApiKeyRepository
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.repository.organization_repository import OrganizationRepository


@pytest.mark.asyncio
async def test_api_key_crud_flow(isolated_database_manager):
    async with isolated_database_manager.local_session() as session:
        org_repo = OrganizationRepository(session)
        api_repo = ApiKeyRepository(session)

        created_org = None
        created_key = None
        try:
            # Create an organization as prerequisite
            created_org = await org_repo.create(
                contact_email=f"org-{uuid.uuid4().hex[:8]}@example.com",
                name=f"Org {uuid.uuid4().hex[:6]}",
                platform_role=PlatformRole.STANDARD,
            )
            await session.commit()

            # Create API key
            valid_prefix = "ak_" + uuid.uuid4().hex[:9]  # total length 12
            created_key = await api_repo.create(
                organization_id=created_org.id,
                key_hash=f"hash-{uuid.uuid4().hex}",
                prefix=valid_prefix,
                status=ApiKeyStatus.ACTIVE,
            )
            await session.commit()

            assert created_key.id is not None
            assert created_key.organization_id == created_org.id
            assert created_key.status == ApiKeyStatus.ACTIVE
            assert created_key.organization is None

            # Get by id
            fetched = await api_repo.get_by_id(created_key.id)
            assert fetched is not None
            assert fetched.id == created_key.id
            assert fetched.organization is None

            # Fetch with organization relation
            fetched = await api_repo.get_by_id_with_relation(created_key.id)
            assert fetched is not None
            assert fetched.id == created_key.id
            assert fetched.organization is not None
            assert fetched.organization.id == created_org.id

            # List by organization
            items = await api_repo.list(organization_id=created_org.id)
            assert any(k.id == created_key.id for k in items)

            # Update status
            updated = await api_repo.update(created_key.id, status=ApiKeyStatus.REVOKED)
            await session.commit()
            assert updated is not None
            assert updated.status == ApiKeyStatus.REVOKED

            # Delete
            deleted = await api_repo.delete(created_org.id, created_key.id)
            await session.commit()
            assert deleted is True
        finally:
            # Ensure session is clean before cleanup if an error occurred
            try:
                await session.rollback()
            except Exception:
                pass
            # Cleanup residue if necessary
            if created_key is not None:
                try:
                    await api_repo.delete(created_org.id, created_key.id)
                except Exception:
                    pass
            if created_org is not None:
                try:
                    await org_repo.delete(created_org.id)
                except Exception:
                    pass
            try:
                await session.commit()
            except Exception:
                pass
