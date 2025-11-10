from datetime import datetime
from uuid import uuid4

import pytest

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.repository.organization_repository import OrganizationRepository
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext


@pytest.fixture
async def main_workflow_context():
    return MainWorkflowContext(
        execution_id=str(uuid4()), start_time=datetime.now(),
        steps_metadata=[], organization_id=uuid4()
    )


@pytest.fixture
async def organization_id():
    """Crée une organisation pour un test et retourne son UUID.

    Nettoyage automatique après le test (delete + commit).
    """
    dbm = DatabaseManager()
    async with dbm.local_session() as session:
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
    async with dbm.local_session() as session:
        repo = OrganizationRepository(session)
        try:
            await repo.delete(created_id)
            await session.commit()
        except Exception:
            await session.rollback()
