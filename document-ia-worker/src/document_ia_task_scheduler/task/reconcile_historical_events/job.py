import asyncio
import logging
import time
from typing import Dict, List, Literal, Optional
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified

from document_ia_infra.data.database import DatabaseManager
from document_ia_infra.data.event.dto.anonymization_enum import AnonymizationStatus
from document_ia_infra.data.event.repository.event import EventRepository
from document_ia_task_scheduler.task.replicate_analytics.replicate_analytics_settings import (
    replicate_analytics_settings,
)

logger = logging.getLogger(__name__)

TargetType = Literal["main", "analytics", "both"]


class ReconcileHistoricalEventsJob:
    """Reconcile and re-anonymize historical DONE and ERROR events in batches."""

    def __init__(
        self,
        batch_size: int = 1000,
        pause_seconds: float = 0.05,
        dry_run: bool = False,
    ) -> None:
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds
        self.dry_run = dry_run

    async def run(self, target: TargetType = "both") -> Dict[str, Dict[str, int]]:
        """Run the reconciliation on the specified target databases.

        Args:
            target: "main", "analytics", or "both".

        Returns:
            Dictionary with statistics per target database.
        """
        targets: List[str] = []
        if target in ("main", "both"):
            targets.append("main")
        if target in ("analytics", "both"):
            targets.append("analytics")

        stats: Dict[str, Dict[str, int]] = {}
        for current_target in targets:
            stats[current_target] = await self._reconcile_target(current_target)

        return stats

    async def _reconcile_target(self, target: str) -> Dict[str, int]:
        """Reconcile events on a single database target."""
        logger.info(
            f"=== Démarrage de la réconciliation ({target.upper()}) | "
            f"Lot: {self.batch_size} | Pause: {self.pause_seconds:.3f}s | "
            f"Dry-run: {self.dry_run} ==="
        )

        db_manager = (
            DatabaseManager()
            if target == "main"
            else DatabaseManager(db_settings=replicate_analytics_settings)
        )

        statuses = [AnonymizationStatus.DONE.value, AnonymizationStatus.ERROR.value]
        processed_count = 0
        success_count = 0
        error_count = 0

        try:
            async with db_manager.local_session() as session:
                event_repository = EventRepository(session)
                total_count = await event_repository.count_events_by_statuses(statuses)

            if total_count == 0:
                logger.info(
                    f"[{target.upper()}] Aucun événement historique à réconcilier."
                )
                return {"total": 0, "processed": 0, "success": 0, "errors": 0}

            total_lots = (total_count + self.batch_size - 1) // self.batch_size
            lot_idx = 0
            start_time = time.monotonic()
            cursor_id: Optional[UUID] = None

            while True:
                async with db_manager.local_session() as session:
                    event_repository = EventRepository(session)
                    events = await event_repository.get_events_by_cursor(
                        statuses=statuses,
                        limit=self.batch_size,
                        after_id=cursor_id,
                    )

                    if not events:
                        break

                    lot_idx += 1
                    lot_success = 0
                    lot_error = 0

                    if self.dry_run:
                        lot_success = len(events)
                    else:
                        for event in events:
                            EventRepository.anonymize_payload(
                                event.event_type, event.event
                            )
                            flag_modified(event, "event")
                            event.anonymization_status = AnonymizationStatus.DONE.value
                            session.add(event)

                        try:
                            await session.commit()
                            lot_success = len(events)
                        except Exception as batch_exc:
                            logger.warning(
                                f"[{target.upper()}] Échec du commit par lot, reprise unitaire: {batch_exc}"
                            )
                            await session.rollback()

                            # Fallback unitaire pour isoler l'erreur éventuelle
                            for event in events:
                                try:
                                    EventRepository.anonymize_payload(
                                        event.event_type, event.event
                                    )
                                    flag_modified(event, "event")
                                    event.anonymization_status = (
                                        AnonymizationStatus.DONE.value
                                    )
                                    session.add(event)
                                    await session.commit()
                                    lot_success += 1
                                except Exception as row_exc:
                                    await session.rollback()
                                    logger.error(
                                        f"[{target.upper()}] Erreur sur l'événement {event.id}: {row_exc}"
                                    )
                                    lot_error += 1

                    success_count += lot_success
                    error_count += lot_error
                    processed_count += len(events)
                    cursor_id = events[-1].id

                    # Calcul des métriques de débit et d'ETA
                    elapsed = time.monotonic() - start_time
                    rate = processed_count / elapsed if elapsed > 0 else 0.0
                    remaining = max(0, total_count - processed_count)
                    eta = remaining / rate if rate > 0 else 0.0
                    pct = (
                        (processed_count / total_count * 100.0)
                        if total_count > 0
                        else 100.0
                    )
                    eta_str = (
                        f"{int(eta // 60)}m{int(eta % 60):02d}s"
                        if eta >= 60
                        else f"{eta:.1f}s"
                    )

                    logger.info(
                        f"[Traitement {target.upper()}] Lot {lot_idx}/{total_lots} "
                        f"({processed_count}/{total_count} - {pct:.1f}%) | "
                        f"Succès: {success_count} | Erreurs: {error_count} | "
                        f"Débit: {rate:.1f} ev/s | ETA: {eta_str}"
                    )

                    if len(events) < self.batch_size:
                        break

                if self.pause_seconds > 0:
                    await asyncio.sleep(self.pause_seconds)

            logger.info(
                f"=== Fin de réconciliation ({target.upper()}) | Total traité: {processed_count} | "
                f"Succès: {success_count} | Erreurs: {error_count} ==="
            )
            return {
                "total": total_count,
                "processed": processed_count,
                "success": success_count,
                "errors": error_count,
            }

        finally:
            await db_manager.dispose_async()
