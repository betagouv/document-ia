"""Reject saturated execution requests before storing files or start events."""

import logging

from document_ia_api.api.exceptions.service_unavailable_exception import (
    capacity_unavailable,
)
from document_ia_infra.redis.admission import admit_execution
from document_ia_infra.redis.redis_manager import redis_manager

logger = logging.getLogger(__name__)


async def check_execution_admission() -> None:
    try:
        connection = await redis_manager.get_connection()
        if connection is None:
            raise RuntimeError("No admission connection")
        await admit_execution(connection)
    except Exception as exc:
        logger.warning("Execution admission refused: %s", type(exc).__name__)
        raise capacity_unavailable() from exc
