import uuid
import pytest

from document_ia_infra.data.database import database_manager
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.repository.organization_repository import OrganizationRepository
from document_ia_infra.data.api_key.repository.api_key import ApiKeyRepository
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus


@pytest.mark.asyncio(scope="session")
class TestOrganizationRepository:
    async def test_create_get_update_delete_organization(self):
        async with database_manager.local_session() as session:
            repo = OrganizationRepository(session)
            created = None
            try:
                # Create
                email = f"org-{uuid.uuid4().hex[:8]}@example.com"
                name = f"Org {uuid.uuid4().hex[:6]}"
                created = await repo.create(
                    contact_email=email,
                    name=name,
                    platform_role=PlatformRole.STANDARD,
                )
                await session.commit()

                assert created.id is not None
                assert created.contact_email == email
                assert created.name == name
                assert created.platform_role == PlatformRole.STANDARD
                assert created.api_keys is None

                # Get by id
                fetched = await repo.get_by_id(created.id)
                assert fetched is not None
                assert fetched.id == created.id
                assert fetched.contact_email == email

                # Update
                new_email = f"updated-{uuid.uuid4().hex[:8]}@example.com"
                new_name = f"Updated {uuid.uuid4().hex[:6]}"
                updated = await repo.update(
                    created.id,
                    contact_email=new_email,
                    name=new_name,
                    platform_role=PlatformRole.PLATFORM_ADMIN,
                )
                await session.commit()

                assert updated is not None
                assert updated.contact_email == new_email
                assert updated.name == new_name
                assert updated.platform_role == PlatformRole.PLATFORM_ADMIN
            finally:
                # Perform cleanup in a fresh session to avoid transaction/loop issues
                async with database_manager.local_session() as clean_session:
                    clean_repo = OrganizationRepository(clean_session)
                    if created is not None:
                        try:
                            await clean_repo.delete(created.id)
                            await clean_session.commit()
                        except Exception:
                            await clean_session.rollback()

    async def test_list_organizations_with_pagination(self):
        async with database_manager.local_session() as session:
            repo = OrganizationRepository(session)
            created_ids: list = []
            try:
                # Seed a couple of orgs for listing
                for _ in range(2):
                    o = await repo.create(
                        contact_email=f"seed-{uuid.uuid4().hex[:8]}@example.com",
                        name=f"Seed {uuid.uuid4().hex[:6]}",
                        platform_role=PlatformRole.STANDARD,
                    )
                    created_ids.append(o.id)
                await session.commit()

                items = await repo.list()
                assert isinstance(items, list)
                # At least the ones we've just created should be present
                item_ids = {x.id for x in items}
                assert set(created_ids).issubset(item_ids)

                # Pagination: limit = 1
                page = await repo.list(limit=1)
                assert len(page) == 1
            finally:
                # Cleanup in a fresh session to avoid cross-loop/transaction issues
                async with database_manager.local_session() as clean_session:
                    clean_repo = OrganizationRepository(clean_session)
                    for oid in created_ids:
                        try:
                            await clean_repo.delete(oid)
                        except Exception:
                            await clean_session.rollback()
                    try:
                        await clean_session.commit()
                    except Exception:
                        await clean_session.rollback()

    async def test_get_with_api_keys_and_cascade_delete(self):
        async with database_manager.local_session() as session:
            org_repo = OrganizationRepository(session)
            key_repo = ApiKeyRepository(session)
            created_org_id = None
            try:
                # Create organization
                created = await org_repo.create(
                    contact_email=f"org-{uuid.uuid4().hex[:8]}@example.com",
                    name=f"Org {uuid.uuid4().hex[:6]}",
                    platform_role=PlatformRole.STANDARD,
                )
                created_org_id = created.id
                await session.commit()

                # Create two API keys for this organization
                for _ in range(2):
                    prefix = "ak_" + uuid.uuid4().hex[:9]  # length 12
                    await key_repo.create(
                        organization_id=created_org_id,
                        key_hash=f"hash-{uuid.uuid4().hex}",
                        prefix=prefix,
                        status=ApiKeyStatus.ACTIVE,
                    )
                await session.commit()

                # Fetch with eager-loaded api_keys
                fetched = await org_repo.get_with_api_keys(created_org_id)
                assert fetched is not None
                assert fetched.api_keys is not None
                assert len(fetched.api_keys) == 2

                # Delete organization (should cascade delete api_keys)
                deleted = await org_repo.delete(created_org_id)
                await session.commit()
                assert deleted is True

                # Verify no api keys remain for this organization
                remaining = await key_repo.list(organization_id=created_org_id)
                assert len(remaining) == 0
            finally:
                # Best-effort cleanup in fresh session if something failed earlier
                if created_org_id is not None:
                    async with database_manager.local_session() as clean_session:
                        clean_repo = OrganizationRepository(clean_session)
                        try:
                            await clean_repo.delete(created_org_id)
                            await clean_session.commit()
                        except Exception:
                            await clean_session.rollback()
