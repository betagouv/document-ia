"""Enregistrement d'un échec terminal décidé par le watchdog.

Le watchdog fence une tentative bloquée : elle ne rapportera donc jamais son propre
échec. Quand toutes les reprises sont épuisées, le consommateur signale l'échec via
ce callback pour que l'exécution n'en reste pas bloquée à ``STARTED``.
"""

import logging
from collections.abc import Mapping
from typing import Any

from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)

from document_ia_worker.workflow.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


async def notify_watchdog_terminal_failure(
    msg_id: str, fields: Mapping[str, Any], reason: str
) -> None:
    """Point d'entrée du callback ``on_terminal_failure`` du consommateur."""
    raw_payload = fields.get("data")
    if not raw_payload:
        logger.warning(
            "Terminal failure for message %s carries no payload; skipping", msg_id
        )
        return

    message = WorkflowExecutionMessage.from_json(raw_payload)
    raw_retries = fields.get("retries")
    retry_count = 0
    if isinstance(raw_retries, int):
        retry_count = raw_retries
    elif isinstance(raw_retries, str) and raw_retries.isdigit():
        retry_count = int(raw_retries)

    manager = WorkflowManager(message, retry_count, is_last_retry=True)
    await manager.record_watchdog_terminal_failure(reason)
