"""Atomic admission of new executions against both asynchronous queues.

Capacity is allocated by XADD in the same Lua invocation as the checks. Existing
work (including webhook delivery and retries) must still be allowed to drain.
"""

import asyncio
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from document_ia_infra.redis.redis_settings import redis_settings


class AdmissionUnavailableError(Exception):
    """Capacity is exhausted or cannot be established safely."""


# No scans over retained history: inspect group lag, PEL summary and at most one
# undelivered entry per queue. Redis TIME makes age independent of API clocks.
ADMISSION_SCRIPT = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local blocked = false
for i = 1, 2 do
    local stream = KEYS[i]
    local state = KEYS[i + 2]
    local group_name = ARGV[i]
    local groups = {}
    if redis.call('EXISTS', stream) == 1 then
        groups = redis.call('XINFO', 'GROUPS', stream)
    end
    local group = nil
    for _, fields in ipairs(groups) do
        local item = {}
        for j = 1, #fields, 2 do item[fields[j]] = fields[j + 1] end
        if item['name'] == group_name then group = item end
    end
    local count = 0
    local oldest = nil
    if group then
        if type(group['lag']) ~= 'number' then
            return redis.error_reply('Admission lag unavailable')
        end
        count = group['lag'] + group['pending']
        local pending = redis.call('XPENDING', stream, group_name)
        if pending[1] > 0 then oldest = pending[2] end
        if group['lag'] > 0 then
            local waiting = redis.call('XRANGE', stream,
                '(' .. group['last-delivered-id'], '+', 'COUNT', 1)
            if #waiting == 0 then
                return redis.error_reply('Admission backlog unavailable')
            end
            if not oldest or tonumber(string.match(waiting[1][1], '^(%d+)')) <
                tonumber(string.match(oldest, '^(%d+)')) then
                oldest = waiting[1][1]
            end
        end
    elseif redis.call('EXISTS', stream) == 1 then
        count = redis.call('XLEN', stream)
        local waiting = redis.call('XRANGE', stream, '-', '+', 'COUNT', 1)
        if #waiting > 0 then oldest = waiting[1][1] end
    end
    local age = 0
    if oldest then
        age = math.max(0, now_ms - tonumber(string.match(oldest, '^(%d+)')))
    end
    local high = tonumber(ARGV[3])
    local low = tonumber(ARGV[4])
    local age_high = tonumber(ARGV[5]) * 1000
    local age_low = tonumber(ARGV[6]) * 1000
    local closed = redis.call('GET', state) == 'closed'
    if count >= high or age >= age_high then
        closed = true
    elseif closed and count <= low and age <= age_low then
        closed = false
    end
    if closed then
        redis.call('SET', state, 'closed')
        blocked = true
    else
        redis.call('DEL', state)
    end
end
if blocked then return {0} end
if ARGV[7] == 'publish' then
    local id = redis.call('XADD', KEYS[1], '*',
        'data', ARGV[8], 'timestamp', ARGV[9], 'retries', '0')
    return {1, id}
end
return {1}
"""


async def admit_execution(
    connection: Redis,
    *,
    data: str | None = None,
    timestamp: str = "",
) -> str | None:
    """Preflight, or atomically allocate capacity by publishing the execution.

    A preflight is advisory only; publication always checks again atomically.
    """
    # redis-py's command mixin also types the synchronous client's eval.
    result = await asyncio.wait_for(
        cast(
            Awaitable[list[object]],
            connection.eval(
                ADMISSION_SCRIPT,
                4,
                redis_settings.EVENT_STREAM_NAME,
                redis_settings.WEBHOOK_STREAM_NAME,
                f"{redis_settings.EVENT_STREAM_NAME}:admission",
                f"{redis_settings.WEBHOOK_STREAM_NAME}:admission",
                redis_settings.EVENT_CONSUMER_GROUP,
                redis_settings.WEBHOOK_CONSUMER_GROUP,
                str(redis_settings.ADMISSION_MAX_OUTSTANDING),
                str(redis_settings.ADMISSION_RESUME_OUTSTANDING),
                str(redis_settings.ADMISSION_MAX_AGE_SECONDS),
                str(redis_settings.ADMISSION_RESUME_AGE_SECONDS),
                "publish" if data is not None else "check",
                data or "",
                timestamp,
            ),
        ),
        timeout=5,
    )
    if not result or result[0] != 1:
        raise AdmissionUnavailableError("Asynchronous capacity exhausted")
    if data is None:
        return None
    message_id = result[1]
    if not isinstance(message_id, str):
        raise AdmissionUnavailableError("Invalid publication response")
    return message_id
