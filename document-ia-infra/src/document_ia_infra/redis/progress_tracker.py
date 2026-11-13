"""Progress tracking and watchdog support for Redis message processing."""

import threading
import time
from contextvars import ContextVar

__all__ = [
    "ProgressTracker",
    "current_progress_tracker",
    "get_current_progress_tracker",
    "record_step_progress",
]


class ProgressTracker:
    """Thread-safe watchdog tracker for single message processing.

    Monitors elapsed total processing time and elapsed time since the last step
    progress update. If either threshold is exceeded, the tracker transitions to
    an unhealthy state and can be aborted to prevent rogue commits (fencing).
    """

    def __init__(
        self,
        msg_id: str,
        max_processing_time_s: float | None = None,
        step_progress_timeout_s: float | None = None,
        execution_id: str | None = None,
        lease_token: str | None = None,
    ) -> None:
        if max_processing_time_s is not None and max_processing_time_s <= 0:
            raise ValueError("max_processing_time_s must be > 0")
        if step_progress_timeout_s is not None and step_progress_timeout_s <= 0:
            raise ValueError("step_progress_timeout_s must be > 0")

        self.msg_id = msg_id
        self.max_processing_time_s = max_processing_time_s
        self.step_progress_timeout_s = step_progress_timeout_s
        self.execution_id = execution_id
        self.lease_token = lease_token

        now = time.monotonic()
        self.start_time: float = now
        self.last_progress_time: float = now
        self.current_step: str | None = None

        self._aborted: bool = False
        self._abort_reason: str | None = None
        self._lock = threading.Lock()

    def record_step(self, step_name: str) -> None:
        """Enregistre l'avancement d'une étape et réinitialise le délai d'inactivité."""
        with self._lock:
            self.last_progress_time = time.monotonic()
            self.current_step = step_name

    def is_healthy(self, now: float | None = None) -> bool:
        """Vérifie si le traitement est en cours et ne dépasse aucun timeout."""
        with self._lock:
            if self._aborted:
                return False
            current = now if now is not None else time.monotonic()
            if (
                self.max_processing_time_s is not None
                and (current - self.start_time) > self.max_processing_time_s
            ):
                return False
            if (
                self.step_progress_timeout_s is not None
                and (current - self.last_progress_time) > self.step_progress_timeout_s
            ):
                return False
            return True

    def check_timeout_reason(self, now: float | None = None) -> str | None:
        """Retourne la raison du dépassement ('workflow_timeout' ou 'step_timeout')."""
        with self._lock:
            if self._abort_reason is not None:
                return self._abort_reason
            current = now if now is not None else time.monotonic()
            if (
                self.max_processing_time_s is not None
                and (current - self.start_time) > self.max_processing_time_s
            ):
                return "workflow_timeout"
            if (
                self.step_progress_timeout_s is not None
                and (current - self.last_progress_time) > self.step_progress_timeout_s
            ):
                return "step_timeout"
            return None

    def abort(self, reason: str = "") -> None:
        """Marque le tracker comme avorté pour stopper le heartbeat et activer le fencing."""
        with self._lock:
            self._aborted = True
            if reason:
                self._abort_reason = reason
            elif self._abort_reason is None:
                current = time.monotonic()
                if (
                    self.max_processing_time_s is not None
                    and (current - self.start_time) > self.max_processing_time_s
                ):
                    self._abort_reason = "workflow_timeout"
                elif (
                    self.step_progress_timeout_s is not None
                    and (current - self.last_progress_time)
                    > self.step_progress_timeout_s
                ):
                    self._abort_reason = "step_timeout"
                else:
                    self._abort_reason = "aborted"

    @property
    def is_aborted(self) -> bool:
        with self._lock:
            return self._aborted

    @property
    def abort_reason(self) -> str | None:
        with self._lock:
            return self._abort_reason


current_progress_tracker: ContextVar[ProgressTracker | None] = ContextVar(
    "current_progress_tracker", default=None
)


def get_current_progress_tracker() -> ProgressTracker | None:
    """Retourne le tracker de progression associé au contexte d'exécution courant."""
    return current_progress_tracker.get()


def record_step_progress(step_name: str) -> None:
    """Notifie l'avancement d'une étape pour le message courant s'il existe."""
    tracker = get_current_progress_tracker()
    if tracker is not None:
        tracker.record_step(step_name)
