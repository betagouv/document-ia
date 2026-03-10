import logging
import time
from abc import ABC
from typing import TypeVar, Generic, Any, Optional

from document_ia_worker.workflow.main_workflow_context import StepMetadata

T = TypeVar("T")
WCT = TypeVar("WCT")


logger = logging.getLogger(__name__)


class BaseStep(ABC, Generic[T]):
    async def execute(self) -> tuple[T, StepMetadata]:
        start = time.perf_counter()
        try:
            await self._prepare_step()
            result, metadata = await self._execute_internal()
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "Step %s executed in %.3f seconds",
                self.__class__.__name__,
                elapsed,
            )
        return result, self._compute_metadata(elapsed, metadata)

    def _compute_metadata(
        self, elapsed: float, custom_metadata: Optional[StepMetadata]
    ) -> StepMetadata:
        if custom_metadata is None:
            return StepMetadata(
                step_name=self.__class__.__name__, execution_time=elapsed
            )
        else:
            custom_metadata.execution_time = elapsed
            return custom_metadata

    def inject_workflow_context(self, context: dict[str, Any]):
        pass

    def get_context_result_key(self) -> str: ...

    # The field is_finished indicates whether the message that is being processed will not be retried.
    # For example, if the message has exceeded the maximum number of retries, is_finished will be True.
    # If the message is a success is_finished will be True as well.
    # In case of a failure that will be retried, is_finished will be False.
    async def cleanup(self, is_last_cleanup: bool):
        pass

    async def _prepare_step(self): ...

    async def _execute_internal(self) -> tuple[T, Optional[StepMetadata]]: ...

    def _get_safe_workflow_context_key(
        self, cls: type[WCT], context: dict[str, Any]
    ) -> WCT:
        not_typed_data = context.get(cls.__name__)
        if not_typed_data is None or not isinstance(not_typed_data, cls):
            raise ValueError(f"{cls.__name__} not found in context")
        return not_typed_data

    def _get_not_mandatory_workflow_context_key(
        self, cls: type[WCT], context: dict[str, Any]
    ) -> WCT | None:
        not_typed_data = context.get(cls.__name__)
        if not_typed_data is None:
            return None
        if not isinstance(not_typed_data, cls):
            raise ValueError(f"{cls.__name__} found in context but has wrong type")
        return not_typed_data
