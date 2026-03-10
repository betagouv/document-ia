import logging
from datetime import datetime, timedelta

from document_ia_infra.data.database import DatabaseManager
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

        async with DatabaseManager().local_session() as session:
            event_repository = EventRepository(session)
            events = await event_repository.get_not_anonymized_events_before(
                before_date=datetime.today() - timedelta(days=retention_days),
            )
            logger.info(f"Found {len(events)} events")
            for event in events:
                try:
                    await event_repository.anonymize_event(event)
                except Exception as e:
                    logger.error(f"Error while anonymizing event: {e}")
                    await event_repository.save_failed_anonymization(event)
