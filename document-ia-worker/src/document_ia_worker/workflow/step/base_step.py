from abc import ABC
from typing import TypeVar, Generic, Any

T = TypeVar("T")
WCT = TypeVar("WCT")


class BaseStep(ABC, Generic[T]):
    async def execute(self) -> T:
        await self._prepare_step()
        return await self._execute_internal()

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

    async def _execute_internal(self) -> T: ...

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
