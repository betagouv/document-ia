import logging
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4

from document_ia_task_scheduler.core.aggregator_log import (
    setup_logging_worker,
    execution_id_var,
    agg_buffer_var,
    start_time_var,
    handle_finish_execution,
)

logger = logging.getLogger(__name__)


class BaseScheduledJob(ABC):
    def __init__(self):
        setup_logging_worker()
        self._agg_token_exec = execution_id_var.set(str(uuid4()))
        self._agg_token_buf = agg_buffer_var.set([])
        self._agg_token_started_at = start_time_var.set(datetime.now(UTC))

    async def execute(self) -> None:
        is_success: bool = True
        err_type: Optional[str] = None
        err_message: Optional[str] = None

        try:
            logger.info(f"Executing {self._get_job_name()}")
            await self._internal_execute()
            logger.info("Execution finished")
        except Exception as e:
            logger.error(f"Error executing {self._get_job_name()}: {e}")
            is_success = False
            err_type = e.__class__.__name__
            err_message = str(e)
            raise
        finally:
            handle_finish_execution(
                logger=logger,
                task_name=self._get_job_name(),
                is_success=is_success,
                token_exec_id=self._agg_token_exec,
                token_buf=self._agg_token_buf,
                token_started_at=self._agg_token_started_at,
                err_type=err_type,
                err_message=err_message,
            )

    @abstractmethod
    async def _internal_execute(self) -> None:
        pass

    @abstractmethod
    def _get_job_name(self) -> str:
        pass
