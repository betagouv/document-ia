from abc import ABC
from typing import TypeVar, Generic, Any

T = TypeVar("T")


class BaseStep(ABC, Generic[T]):
    async def execute(self) -> T:
        await self._prepare_step()
        return await self._execute_internal()

    def inject_workflow_context(self, context: dict[str, Any]):
        pass

    def get_context_result_key(self) -> str: ...

    async def cleanup(self):
        pass

    async def _prepare_step(self): ...

    async def _execute_internal(self) -> T: ...
