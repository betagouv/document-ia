"""Background and startup temporary file sweeper for Document IA Worker.

Ensures that orphaned temporary directories (abandoned post-crash, watchdog
aborts, OOM or unexpected worker termination) and expired OpenAI replay payloads
are deterministically and securely removed from the host filesystem.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path

from document_ia_infra.core.file.safe_path import (
    DEFAULT_SANDBOX_BASE,
    safe_cleanup_directory,
    validate_execution_id,
)
from document_ia_infra.exception.security_exception import InvalidUUIDException
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.stream_delivery import StreamDelivery
from document_ia_worker.workflow.step.llm_extract_document.settings import (
    settings as llm_settings,
)

logger = logging.getLogger(__name__)

DEFAULT_ORPHAN_GRACE_PERIOD_S: float = 900.0  # 15 minutes
DEFAULT_SWEEP_INTERVAL_S: float = 600.0  # 10 minutes
DEFAULT_REPLAY_RETENTION_HOURS: float = 24.0  # 24 hours


class ActiveExecutionTracker:
    """Thread-safe in-memory registry of execution IDs currently being processed on this worker.

    Used by the sweeper to guarantee that files belonging to an in-flight workflow
    are never swept.
    """

    _active_ids: set[str] = set()
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def add(cls, execution_id: str) -> None:
        """Register an execution_id as actively running."""
        with cls._lock:
            cls._active_ids.add(execution_id)
            logger.debug(
                "ActiveExecutionTracker: added %s (total: %d)",
                execution_id,
                len(cls._active_ids),
            )

    @classmethod
    def remove(cls, execution_id: str) -> None:
        """Deregister an execution_id when its processing completes or terminates."""
        with cls._lock:
            cls._active_ids.discard(execution_id)
            logger.debug(
                "ActiveExecutionTracker: removed %s (total: %d)",
                execution_id,
                len(cls._active_ids),
            )

    @classmethod
    def is_active(cls, execution_id: str) -> bool:
        """Check whether an execution_id is currently active on this worker."""
        with cls._lock:
            return execution_id in cls._active_ids

    @classmethod
    def active_ids(cls) -> set[str]:
        """Return a copy of all active execution IDs."""
        with cls._lock:
            return set(cls._active_ids)

    @classmethod
    def clear(cls) -> None:
        """Clear all active executions (useful for test isolation)."""
        with cls._lock:
            cls._active_ids.clear()


class TempFileSweeper:
    """Sweeper service for recovering and deleting abandoned temporary files and directories."""

    def __init__(
        self,
        sandbox_base: Path = DEFAULT_SANDBOX_BASE,
        replay_dir: Path | str | None = None,
        redis_manager: RedisManager | None = None,
        grace_period_s: float = DEFAULT_ORPHAN_GRACE_PERIOD_S,
        replay_retention_hours: float = DEFAULT_REPLAY_RETENTION_HOURS,
    ) -> None:
        self.sandbox_base: Path = Path(sandbox_base)
        self.replay_dir: Path = Path(
            replay_dir
            if replay_dir is not None
            else llm_settings.OPENAI_REPLAY_PAYLOAD_SAVE_PATH
        )
        self.redis_manager: RedisManager | None = redis_manager
        self.grace_period_s: float = grace_period_s
        self.replay_retention_hours: float = replay_retention_hours

    async def is_execution_active(
        self,
        execution_id: str,
        redis_manager: RedisManager | None = None,
    ) -> bool:
        """Check whether an execution is active locally or holds a live Redis lease on the cluster."""
        if ActiveExecutionTracker.is_active(execution_id):
            return True

        rm = redis_manager or self.redis_manager
        if rm is not None:
            try:
                conn = await rm.get_connection()
                if conn is not None:
                    lease_key = StreamDelivery.execution_lease_key(execution_id)
                    exists = await conn.exists(lease_key)
                    if exists:
                        return True
            except Exception as exc:
                logger.warning(
                    "Failed to check Redis lease for execution %s: %s",
                    execution_id,
                    exc,
                )

        return False

    async def sweep_sandbox(
        self,
        sandbox_base: Path | None = None,
        max_age_seconds: float | None = None,
        redis_manager: RedisManager | None = None,
    ) -> int:
        """Scan sandbox_base and securely delete abandoned orphaned execution directories.

        Protection rules:
        1. Ignored if directory name is not a valid UUID (protects non-execution folders like model caches).
        2. Skipped if execution is currently active locally or in Redis cluster.
        3. Skipped if directory age (mtime) is under grace period (allows retries/restarts).
        4. When age exceeds grace period and execution is inactive, safe_cleanup_directory is invoked.

        Returns:
            Number of orphaned directories purged.
        """
        base = sandbox_base or self.sandbox_base
        grace_period = (
            max_age_seconds if max_age_seconds is not None else self.grace_period_s
        )
        rm = redis_manager or self.redis_manager

        if not base.exists():
            return 0

        purged_count = 0
        now = time.time()

        try:
            entries = list(base.iterdir())
        except OSError as exc:
            logger.warning("Could not list sandbox base directory %s: %s", base, exc)
            return 0

        for entry in entries:
            # If an entry is a symlink directly in sandbox base, remove it safely
            if entry.is_symlink():
                logger.warning("Removing unexpected symlink in sandbox base: %s", entry)
                try:
                    entry.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove symlink %s: %s", entry, exc)
                continue

            if not entry.is_dir():
                continue

            # 1. Enforce standard UUID format; skip and protect any other folder (e.g., .models, cache)
            try:
                validate_execution_id(entry.name)
            except InvalidUUIDException:
                logger.debug("Skipping non-UUID directory in sandbox: %s", entry.name)
                continue

            # 2. Check active execution (in-memory tracker or Redis cluster lease)
            if await self.is_execution_active(entry.name, rm):
                logger.debug("Execution %s is active; skipping sweep", entry.name)
                continue

            # 3. Check mtime against grace period
            try:
                mtime = entry.stat().st_mtime
            except OSError as exc:
                logger.warning("Failed to stat sandbox directory %s: %s", entry, exc)
                continue

            age_seconds = now - mtime
            if age_seconds < grace_period:
                logger.debug(
                    "Execution directory %s is in grace period (age=%.1fs < %.1fs); skipping",
                    entry.name,
                    age_seconds,
                    grace_period,
                )
                continue

            # 4. Directory is orphaned and grace period has elapsed -> purge
            logger.info(
                "Purging abandoned orphaned execution sandbox: %s (age=%.1fs, grace_period=%.1fs)",
                entry,
                age_seconds,
                grace_period,
            )
            try:
                safe_cleanup_directory(entry, sandbox_root=entry)
                purged_count += 1
            except Exception as exc:
                logger.warning("Failed to sweep orphaned directory %s: %s", entry, exc)

        return purged_count

    def sweep_replay_payloads(
        self,
        replay_dir: Path | str | None = None,
        max_age_hours: float | None = None,
    ) -> int:
        """Scan OpenAI replay directory and delete payloads older than retention limit.

        Returns:
            Number of expired JSON payload files purged.
        """
        target_dir = Path(replay_dir if replay_dir is not None else self.replay_dir)
        retention_hours = (
            max_age_hours if max_age_hours is not None else self.replay_retention_hours
        )
        max_age_seconds = retention_hours * 3600.0

        if not target_dir.exists():
            return 0

        purged_count = 0
        now = time.time()

        try:
            files = list(target_dir.glob("*.json"))
        except OSError as exc:
            logger.warning("Could not list replay directory %s: %s", target_dir, exc)
            return 0

        for file_path in files:
            if file_path.is_symlink():
                logger.warning(
                    "Removing unexpected symlink in replay dir: %s", file_path
                )
                try:
                    file_path.unlink()
                except OSError as exc:
                    logger.warning("Failed to remove symlink %s: %s", file_path, exc)
                continue

            try:
                mtime = file_path.stat().st_mtime
            except OSError as exc:
                logger.warning("Failed to stat replay file %s: %s", file_path, exc)
                continue

            age_seconds = now - mtime
            if age_seconds > max_age_seconds:
                logger.info(
                    "Purging expired OpenAI replay payload: %s (age=%.1fh > %.1fh)",
                    file_path.name,
                    age_seconds / 3600.0,
                    retention_hours,
                )
                try:
                    file_path.unlink(missing_ok=True)
                    purged_count += 1
                except OSError as exc:
                    logger.warning(
                        "Failed to unlink replay payload %s: %s", file_path, exc
                    )

        return purged_count

    async def startup_cleanup(self) -> None:
        """Perform an initial cleanup on worker startup to purge post-crash orphans."""
        logger.info(
            "[sweeper] Running startup cleanup of orphaned temporary directories..."
        )
        try:
            purged_dirs = await self.sweep_sandbox()
            purged_replays = self.sweep_replay_payloads()
            logger.info(
                "[sweeper] Startup cleanup finished: %d orphaned sandboxes purged, %d expired replay payloads purged",
                purged_dirs,
                purged_replays,
            )
        except Exception as exc:
            logger.error("[sweeper] Error during startup cleanup: %s", exc)

    async def run_periodic_sweep(
        self,
        stop_event: asyncio.Event,
        interval_seconds: float = DEFAULT_SWEEP_INTERVAL_S,
    ) -> None:
        """Periodic background task running during the lifecycle of the worker."""
        logger.info(
            "[sweeper] Starting periodic background temp sweeper (interval=%.1fs, grace_period=%.1fs)",
            interval_seconds,
            self.grace_period_s,
        )

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                # If stop_event was signaled, exit the sweep loop gracefully
                break
            except TimeoutError:
                # Interval elapsed, proceed to sweep
                pass

            try:
                purged_dirs = await self.sweep_sandbox()
                purged_replays = self.sweep_replay_payloads()
                if purged_dirs > 0 or purged_replays > 0:
                    logger.info(
                        "[sweeper] Periodic sweep finished: %d sandboxes purged, %d replay payloads purged",
                        purged_dirs,
                        purged_replays,
                    )
            except Exception as exc:
                logger.error(
                    "[sweeper] Unexpected error during periodic sweep: %s", exc
                )

        logger.info("[sweeper] Periodic background temp sweeper stopped")
