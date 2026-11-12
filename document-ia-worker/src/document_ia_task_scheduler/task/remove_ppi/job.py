import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_task_scheduler.core.base_scheduled_job import BaseScheduledJob
from document_ia_task_scheduler.task.remove_ppi.remove_ppi_settings import (
    remove_ppi_settings,
)

logger = logging.getLogger(__name__)


class RemovePPI(BaseScheduledJob):
    def _get_job_name(self) -> str:
        return "RemovePPI"

    async def _internal_execute(self) -> None:
        retention_days = remove_ppi_settings.EVENT_STORE_PPI_RETENTION_DAYS
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        batch_size = remove_ppi_settings.EVENT_STORE_PPI_BATCH_SIZE

        success_count = 0
        error_count = 0
        failed_ids: set[UUID] = set()

        async with DatabaseManager().local_session() as session:
            event_repository = EventRepository(session)

            while True:
                events = await event_repository.get_events_to_anonymize(
                    before_date=cutoff_date,
                    statuses=[
                        AnonymizationStatus.PENDING.value,
                        AnonymizationStatus.ERROR.value,
                    ],
                    limit=batch_size,
                    exclude_ids=list(failed_ids) if failed_ids else None,
                )
                if not events:
                    break

                for event in events:
                    event_id = event.id
                    try:
                        await event_repository.anonymize_event(event)
                        success_count += 1
                    except Exception as e:
                        logger.error(
                            f"Error while anonymizing event {event_id}: {type(e).__name__}"
                        )
                        failed_ids.add(event_id)
                        error_count += 1
                        try:
                            await event_repository.save_failed_anonymization(event_id)
                        except Exception as save_err:
                            logger.error(
                                f"Failed to mark event {event_id} as ERROR: {type(save_err).__name__}"
                            )

                if len(events) < batch_size:
                    break

            oldest_age = await event_repository.get_oldest_pending_event_age_seconds(
                before_date=cutoff_date
            )
            lag_value = oldest_age if oldest_age is not None else 0.0
            logger.info(
                f"event_purge operation=lag outcome=oldest_pending_age_seconds value={lag_value:.2f}"
            )

            logger.info(
                f"event_purge operation=purge outcome=success value={success_count}"
            )
            logger.info(
                f"event_purge operation=purge outcome=error value={error_count}"
            )
