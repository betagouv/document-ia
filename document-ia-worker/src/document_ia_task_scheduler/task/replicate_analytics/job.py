import copy
import logging

from sqlalchemy import select

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.entity.event_entity import EventEntity
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_infra.data.organization.entity.organization import OrganizationEntity
from document_ia_infra.data.organization.repository.organization_repository import (
    OrganizationRepository,
)
from document_ia_task_scheduler.core.base_scheduled_job import BaseScheduledJob
from document_ia_task_scheduler.task.replicate_analytics.replicate_analytics_settings import (
    replicate_analytics_settings,
)

logger = logging.getLogger(__name__)


class ReplicateAnalytics(BaseScheduledJob):
    """Replicate data from the main database to the analytics database.

    - organization: full, idempotent replication (upsert), no anonymization.
    - event_store: incremental replication from the cursor on the
      destination (``created_at >= replication_cursor``). Rows already replicated are
      skipped gracefully via ``ON CONFLICT (id) DO NOTHING``.
    """

    def _get_job_name(self) -> str:
        return "ReplicateAnalytics"

    async def _internal_execute(self) -> None:
        # The analytics schema is owned by Alembic (applied by the API on
        # startup via migration_service.auto_migrate_analytics), so the tables
        # are expected to already exist here.
        source_manager = DatabaseManager()
        dest_manager = DatabaseManager(db_settings=replicate_analytics_settings)
        try:
            await self._replicate_organizations(source_manager, dest_manager)
            await self._replicate_events(source_manager, dest_manager)
        except Exception as e:
            logger.error(f"Error while replicating data: {e}")
        finally:
            await dest_manager.dispose_async()
            await source_manager.dispose_async()

    async def _replicate_organizations(
        self, source_manager: DatabaseManager, dest_manager: DatabaseManager
    ) -> None:
        async with source_manager.local_session() as source_session:
            result = await source_session.execute(select(OrganizationEntity))
            orgs = [
                self._to_replicated_organization(org) for org in result.scalars().all()
            ]

        async with dest_manager.local_session() as dest_session:
            org_repository = OrganizationRepository(dest_session)
            # Unitary upsert per row is deliberate: organization is a small
            # reference table (max ~1000 rows), so a full row-by-row upsert is
            # simple and fast enough here; no need for a bulk statement.
            for org in orgs:
                await org_repository.upsert(org)
            await dest_session.commit()

        logger.info(f"Replicated {len(orgs)} organizations")

    async def _replicate_events(
        self, source_manager: DatabaseManager, dest_manager: DatabaseManager
    ) -> None:
        batch_size = replicate_analytics_settings.EVENT_BATCH_SIZE

        async with dest_manager.local_session() as dest_session:
            cursor = await EventRepository(dest_session).get_replication_cursor()

        total_replicated = 0
        while True:
            async with source_manager.local_session() as source_session:
                events = await EventRepository(source_session).get_events_created_after(
                    after=cursor, limit=batch_size
                )

            if not events:
                break

            events = [self._to_replicated_event(event) for event in events]
            try:
                async with dest_manager.local_session() as dest_session:
                    await EventRepository(dest_session).bulk_insert_events(events)
                total_replicated += len(events)
            except Exception as e:
                logger.error(f"Error while replicating events batch: {e}")

            if len(events) < batch_size:
                break

            # Advance the cursor to the last event's created_at. The next query
            # (created_at >= cursor) re-reads only the few events sharing that
            # timestamp (deduplicated by ON CONFLICT). Since far fewer than
            # batch_size events share a created_at, a full batch always spans
            # several timestamps, so the cursor strictly advances and the loop
            # terminates.
            cursor = events[-1].created_at

        logger.info(f"Replicated {total_replicated} events")

    @staticmethod
    def _to_replicated_organization(org: OrganizationEntity) -> OrganizationEntity:
        # Replicate on a deep copy so the source entity is never touched.
        # Organizations are copied as-is (no anonymization).
        return copy.deepcopy(org)

    @staticmethod
    def _to_replicated_event(event: EventEntity) -> EventEntity:
        # Copy all columns generically, then apply only the intentional
        # transforms: anonymize the payload and mark it as anonymized.
        new_event = copy.deepcopy(event)

        # Anonymize the copy's payload (in place). Working on new_event.event
        # (the deep copy), not event.event, keeps the source entity untouched.
        EventRepository.anonymize_payload(new_event.event_type, new_event.event)
        new_event.anonymization_status = AnonymizationStatus.DONE.value

        return new_event
