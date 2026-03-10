from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone, UTC
from logging import Filter, LogRecord, Handler
from typing import Any, Dict, List, Optional

from document_ia_worker.workflow.main_workflow_context import StepMetadata

execution_id_var: ContextVar[Optional[str]] = ContextVar(
    "worker_execution_id", default=None
)
agg_buffer_var: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "worker_agg_buffer", default=None
)
start_time_var: ContextVar[Optional[datetime]] = ContextVar(
    "worker_start_time", default=None
)


class ContextExecutionIdFilter(Filter):
    """Inject execution id in every LogRecord if present inside contextvar."""

    def filter(self, record: LogRecord) -> bool:
        eid = execution_id_var.get()
        record.execution_id = eid or ""
        return True


class WorkerAggregatorHandler(Handler):
    """Handler qui copie un log en dict dans le buffer d'agrégation, si on est dans un contexte d'exécution."""

    def emit(self, record: LogRecord) -> None:
        buf = agg_buffer_var.get()
        if buf is None:
            return
        try:
            log_dict: Dict[str, Any] = {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat()
                + "Z",
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
                "pathname": record.pathname,
                "lineno": record.lineno,
                "funcName": record.funcName,
                "execution_id": getattr(record, "execution_id", None),
            }
            buf.append(log_dict)
        except Exception:
            # Ne pas interrompre le flux en cas d'erreur de collecte
            pass


def setup_logging_worker() -> None:
    """Add (idempotently) the aggregation handler to the worker's root logger."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, WorkerAggregatorHandler):
            return
    handler = WorkerAggregatorHandler()
    handler.setLevel(logging.DEBUG)
    handler.addFilter(ContextExecutionIdFilter())
    root.addHandler(handler)


def write_worker_aggregated_entry(entry: Dict[str, Any], tags: dict[str, Any]) -> None:
    try:
        agg_logger = logging.getLogger("aggregator")
        agg_logger.info(json.dumps(entry), extra={"tags": tags})
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Failed to write worker aggregator entry: {e}"
        )


def handle_finish_execution(
    logger: logging.Logger,
    workflow_id: str,
    is_success: bool,
    retry_count: int,
    workflow_steps: List[str],
    token_exec_id: Token[Any],
    token_buf: Token[Any],
    token_started_at: Token[Any],
    err_type: Optional[str] = None,
    err_message: Optional[str] = None,
    failed_step: Optional[str] = None,
    workflow_metadata: Optional[list[StepMetadata]] = None,
) -> None:
    # Write aggregated log entry for this execution
    try:
        finished_at = datetime.now(UTC)
        logs = agg_buffer_var.get() or []
        if start_time_var.get() is None:
            start_time = datetime.now()
        else:
            start_time = start_time_var.get()

        assert start_time is not None

        elapsed_time_ms = int((finished_at - start_time).total_seconds() * 1000)

        entry: dict[str, Any] = {
            "execution_id": execution_id_var.get(),
            "workflow_id": workflow_id,
            "status": is_success and "succeeded" or "failed",
            "retry_count": retry_count,
            "steps": workflow_steps,
            "started_at": start_time.isoformat() + "Z",
            "finished_at": finished_at.isoformat() + "Z",
            "elapsed_time_ms": elapsed_time_ms,
            "logs": logs,
            "workflow_metadata": [
                meta.model_dump(mode="json") for meta in (workflow_metadata or [])
            ],
        }
        if not is_success:
            entry.update(
                {
                    "error_type": err_type,
                    "error_message": err_message,
                    "failed_step": failed_step or "unknown",
                }
            )

        tags = {
            "workflow_id": workflow_id,
            "status": entry["status"],
            "retry_count": entry["retry_count"],
        }
        write_worker_aggregated_entry(entry, tags)
    except Exception as log_e:
        logger.error(f"Failed to write aggregated worker log: {log_e}")
    finally:
        # Reset ContextVars to avoid leaking into other executions
        try:
            agg_buffer_var.reset(token_buf)
            execution_id_var.reset(token_exec_id)
            start_time_var.reset(token_started_at)
        except Exception:
            pass
