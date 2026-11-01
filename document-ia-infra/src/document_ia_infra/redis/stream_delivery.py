"""Redis delivery primitives, deliberately independent of handler/error policy.

Clients are borrowed: the application/RedisManager that created them closes them.
Copy-before-ACK is atomic and idempotent even when a successful reply is lost.
Source entries and their copies must not be trimmed before pending recovery.
"""

import asyncio
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from document_ia_infra.redis.delivery_metrics import delivery_metric
from document_ia_infra.redis.redis_settings import redis_settings

_COPY_ONCE_LUA = """
local target = KEYS[1]
local orig = ARGV[1]
local existing = redis.call('XRANGE', target, ARGV[2], '+')
for _, e in ipairs(existing) do
  local f = e[2]
  for i = 1, #f, 2 do
    if f[i] == 'original_id' and f[i+1] == orig then
      return {0, e[1]}
    end
  end
end
local args = {}
for i = 3, #ARGV do table.insert(args, ARGV[i]) end
local id = redis.call('XADD', target, '*', unpack(args))
return {1, id}
"""


class StreamDelivery:
    """Concrete operations for one stream/group, with no scheduling or retries."""

    def __init__(self, stream: str, group: str, consumer: str):
        self.stream = stream
        self.group = group
        self.consumer = consumer

    async def ensure_group(self, redis: Redis, start: str) -> None:
        try:
            await redis.xgroup_create(
                name=self.stream, groupname=self.group, id=start, mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(self, redis: Redis, count: int, block: int) -> Any:
        if not await self._recovery_slot(redis, "read"):
            await asyncio.sleep(
                min(redis_settings.STREAM_RECOVERY_INTERVAL_MS / 1000, 1)
            )
            return []
        if redis_settings.STREAM_RECOVERY_INTERVAL_MS:
            count = 1
            block = min(block, 1000)
        return await redis.xreadgroup(
            self.group,
            self.consumer,
            streams={self.stream: ">"},
            count=count,
            block=block,
        )

    async def claim(self, redis: Redis, idle_ms: int, start: str, count: int) -> Any:
        if not await self._recovery_slot(redis, "claim"):
            return start, [], []
        if redis_settings.STREAM_RECOVERY_INTERVAL_MS:
            count = 1
        result = await redis.xautoclaim(
            self.stream,
            self.group,
            self.consumer,
            idle_ms,
            start,
            count=count,
        )
        delivery_metric(self.stream, "reclaim", "success", len(result[1]))
        return result

    async def _recovery_slot(self, redis: Redis, operation: str) -> bool:
        interval = redis_settings.STREAM_RECOVERY_INTERVAL_MS
        if not interval:
            return True
        # Shared per stream and operation, not multiplied by instance count.
        return bool(
            await redis.set(
                f"{self.stream}:recovery:{operation}", "1", nx=True, px=interval
            )
        )

    async def ack(self, redis: Redis, entry_id: str) -> None:
        try:
            await redis.xack(self.stream, self.group, entry_id)
        except Exception:
            delivery_metric(self.stream, "ack", "error")
            raise
        delivery_metric(self.stream, "ack", "success")

    async def refresh(self, redis: Redis, ids: set[Any]) -> None:
        if ids:
            await redis.xclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=0,
                message_ids=list(ids),
                justid=True,
            )

    async def copy_once(
        self,
        redis: Redis,
        target: str,
        entry_id: str,
        fields: dict[str, Any],
        *,
        minimum: str = "0-0",
    ) -> bool:
        payload = {**fields, "original_id": str(entry_id)}
        argv = [str(entry_id), minimum]
        for key, value in payload.items():
            argv.extend((str(key), str(value)))
        # redis-py's shared command mixin also types the synchronous client.
        operation = "dlq" if target == f"{self.stream}:dlq" else "retry"
        try:
            result = await cast(
                Awaitable[Any], redis.eval(_COPY_ONCE_LUA, 1, target, *argv)
            )
        except Exception:
            delivery_metric(self.stream, operation, "error")
            raise
        delivery_metric(self.stream, operation, "created" if result[0] else "existing")
        return True

    async def requeue(
        self, redis: Redis, entry_id: str, fields: dict[str, Any], retries: int
    ) -> bool:
        return await self.copy_once(
            redis,
            self.stream,
            entry_id,
            {**fields, "retries": str(retries)},
            minimum=str(entry_id),
        )

    async def retain(self, redis: Redis, entry_id: str, fields: dict[str, Any]) -> bool:
        return await self.copy_once(redis, f"{self.stream}:dlq", entry_id, fields)
