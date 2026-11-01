"""Bounded Redis retention and explicitly requested, admission-checked DLQ replay.

Run with ``python -m document_ia_infra.redis.maintenance``. The default is a
read-only snapshot. No payload or error contents are printed, including on error.
"""

import argparse
import asyncio
import json
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis

from document_ia_infra.redis.admission import ADMISSION_SCRIPT
from document_ia_infra.redis.redis_settings import redis_settings

# A retained prefix is removable only strictly before EVERY group's last
# delivered ID and oldest pending ID. No group means no completion evidence.
# Keep the boundary itself, including the last-delivered ID used for lag tracking.
_BOUNDARY_LUA = """
local function before(a, b)
    local am, as = string.match(a, '^(%d+)%-(%d+)$')
    local bm, bs = string.match(b, '^(%d+)%-(%d+)$')
    if not am or not bm then return false end
    if tonumber(am) ~= tonumber(bm) then return tonumber(am) < tonumber(bm) end
    return tonumber(as) < tonumber(bs)
end
local function boundary(stream)
    if redis.call('EXISTS', stream) == 0 then return '0-0', 0, 0, 0 end
    local groups = redis.call('XINFO', 'GROUPS', stream)
    if #groups == 0 then
        local first = redis.call('XRANGE', stream, '-', '+', 'COUNT', 1)
        local t = redis.call('TIME')
        local age = 0
        if #first > 0 then
            age = math.max(0, tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
                - tonumber(string.match(first[1][1], '^(%d+)')))
        end
        return '0-0', 0, redis.call('XLEN', stream), age
    end
    local limit = nil
    local pending_count, lag, oldest = 0, 0, nil
    for _, fields in ipairs(groups) do
        local g = {}
        for j = 1, #fields, 2 do g[fields[j]] = fields[j + 1] end
        if type(g['lag']) ~= 'number' then
            error('Retention lag unavailable')
        end
        local id = g['last-delivered-id']
        local p = redis.call('XPENDING', stream, g['name'])
        if p[1] > 0 then
            if before(p[2], id) then id = p[2] end
            if not oldest or before(p[2], oldest) then oldest = p[2] end
        end
        if g['lag'] > 0 then
            local waiting = redis.call('XRANGE', stream,
                '(' .. g['last-delivered-id'], '+', 'COUNT', 1)
            if #waiting == 0 then error('Backlog unavailable') end
            if not oldest or before(waiting[1][1], oldest) then oldest = waiting[1][1] end
        end
        pending_count = pending_count + p[1]
        lag = lag + g['lag']
        if not limit or before(id, limit) then limit = id end
    end
    local age = 0
    if oldest then
        local t = redis.call('TIME')
        age = math.max(0, tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
            - tonumber(string.match(oldest, '^(%d+)')))
    end
    return limit, pending_count, lag, age
end
"""

RETENTION_SCRIPT = (
    _BOUNDARY_LUA
    + """
local limit, pending_count, lag, age = boundary(KEYS[1])
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local completed_cutoff = string.format('%.0f-0', math.max(0, now_ms - tonumber(ARGV[1]) * 1000))
local dlq_cutoff = string.format('%.0f-0', math.max(0, now_ms - tonumber(ARGV[2]) * 1000))
local batch = tonumber(ARGV[3])
local deleted, dlq_deleted = 0, 0
local dlq_limit = nil
if redis.call('EXISTS', KEYS[2]) == 1 then
    local groups = redis.call('XINFO', 'GROUPS', KEYS[2])
    if #groups > 0 then dlq_limit = boundary(KEYS[2]) end
end
-- Inspect at most batch DLQ entries, even when the oldest is still protected.
for _, e in ipairs(redis.call('XRANGE', KEYS[2], '-', '(' .. dlq_cutoff, 'COUNT', batch)) do
    local original = nil
    for j = 1, #e[2], 2 do
        if e[2][j] == 'original_id' then original = e[2][j + 1] end
    end
    if original and before(original, limit) and
        (not dlq_limit or before(e[1], dlq_limit)) then
        if ARGV[4] == 'apply' then redis.call('XDEL', KEYS[2], e[1]) end
        dlq_deleted = dlq_deleted + 1
    end
end
if before(limit, completed_cutoff) then completed_cutoff = limit end
if completed_cutoff ~= '0-0' then
    for _, e in ipairs(redis.call('XRANGE', KEYS[1], '-', '(' .. completed_cutoff, 'COUNT', batch)) do
        if ARGV[4] == 'apply' then redis.call('XDEL', KEYS[1], e[1]) end
        deleted = deleted + 1
    end
end
return {pending_count, lag, age, redis.call('XLEN', KEYS[1]),
    redis.call('XLEN', KEYS[2]), deleted, dlq_deleted}
"""
)

# Reuse exactly the API admission check (including shared hysteresis). XADD and
# DLQ deletion share a script: a lost reply cannot cause a second manual replay.
REPLAY_SCRIPT = (
    _BOUNDARY_LUA
    + """
local entry = redis.call('XRANGE', KEYS[6], ARGV[12], ARGV[12], 'COUNT', 1)
if #entry == 0 then return redis.error_reply('DLQ entry absent') end
local fields = {}
for j = 1, #entry[1][2], 2 do fields[entry[1][2][j]] = entry[1][2][j + 1] end
local original = fields['original_id']
local groups = redis.call('XINFO', 'GROUPS', KEYS[5])
if not original or #groups == 0 then
    return redis.error_reply('Original delivery not confirmed complete')
end
for _, fields in ipairs(groups) do
    local g = {}
    for j = 1, #fields, 2 do g[fields[j]] = fields[j + 1] end
    if before(g['last-delivered-id'], original) or
        #redis.call('XPENDING', KEYS[5], g['name'], original, original, 1) > 0 then
        return redis.error_reply('Original delivery not confirmed complete')
    end
end
if #redis.call('XINFO', 'GROUPS', KEYS[6]) > 0 then
    return redis.error_reply('DLQ consumer groups require separate reconciliation')
end
if not fields['data'] then return redis.error_reply('DLQ payload absent') end
local function admission()
"""
    + ADMISSION_SCRIPT
    + """
end
local result = admission()
if result[1] ~= 1 then return redis.error_reply('Admission closed') end
if not redis.call('SET', KEYS[5] .. ':recovery:replay', '1', 'NX', 'PX', ARGV[13]) then
    return redis.error_reply('Replay rate limited')
end
local id = redis.call('XADD', KEYS[5], '*', 'data', fields['data'],
    'retries', '0', 'replayed_from', ARGV[12])
redis.call('XDEL', KEYS[6], ARGV[12])
return id
"""
)


async def maintain(redis: Redis, stream: str, *, apply: bool = False) -> dict[str, int]:
    result = await cast(
        Awaitable[list[int]],
        redis.eval(
            RETENTION_SCRIPT,
            2,
            stream,
            f"{stream}:dlq",
            str(redis_settings.STREAM_COMPLETED_RETENTION_SECONDS),
            str(redis_settings.STREAM_DLQ_RETENTION_SECONDS),
            str(redis_settings.STREAM_CLEANUP_BATCH_SIZE),
            "apply" if apply else "check",
        ),
    )
    return dict(
        zip(
            (
                "pending",
                "lag",
                "oldest_outstanding_ms",
                "retained",
                "dlq",
                "completed_eligible",
                "dlq_eligible",
            ),
            result,
            strict=True,
        )
    )


async def replay(redis: Redis, stream: str, entry_id: str) -> str:
    if stream not in {
        redis_settings.EVENT_STREAM_NAME,
        redis_settings.WEBHOOK_STREAM_NAME,
    }:
        raise ValueError("Unknown stream")
    return await cast(
        Awaitable[str],
        redis.eval(
            REPLAY_SCRIPT,
            6,
            redis_settings.EVENT_STREAM_NAME,
            redis_settings.WEBHOOK_STREAM_NAME,
            f"{redis_settings.EVENT_STREAM_NAME}:admission",
            f"{redis_settings.WEBHOOK_STREAM_NAME}:admission",
            stream,
            f"{stream}:dlq",
            redis_settings.EVENT_CONSUMER_GROUP,
            redis_settings.WEBHOOK_CONSUMER_GROUP,
            str(redis_settings.ADMISSION_MAX_OUTSTANDING),
            str(redis_settings.ADMISSION_RESUME_OUTSTANDING),
            str(redis_settings.ADMISSION_MAX_AGE_SECONDS),
            str(redis_settings.ADMISSION_RESUME_AGE_SECONDS),
            "check",
            "",
            "",
            str(redis_settings.ADMISSION_MAX_RETAINED),
            str(redis_settings.ADMISSION_RESUME_RETAINED),
            entry_id,
            str(max(1000, redis_settings.STREAM_RECOVERY_INTERVAL_MS)),
        ),
    )


async def _main(args: argparse.Namespace) -> None:
    async with Redis.from_url(  # type: ignore[reportUnknownMemberType]
        redis_settings.get_redis_url(),
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    ) as redis:
        if args.replay_id:
            await replay(redis, args.stream, args.replay_id)
            print(json.dumps({"replayed": 1}))
        else:
            result: dict[str, Any] = {}
            for stream in (
                redis_settings.EVENT_STREAM_NAME,
                redis_settings.WEBHOOK_STREAM_NAME,
            ):
                result[stream] = await maintain(redis, stream, apply=args.apply)
            result["applied"] = args.apply
            print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Enable retention or replay writes"
    )
    parser.add_argument(
        "--replay-id",
        help="Replay exactly one DLQ entry; requires --apply and --stream",
    )
    parser.add_argument(
        "--stream",
        choices=(redis_settings.EVENT_STREAM_NAME, redis_settings.WEBHOOK_STREAM_NAME),
    )
    args = parser.parse_args()
    if args.replay_id and not (args.apply and args.stream):
        parser.error("Replay requires --apply and --stream")
    try:
        asyncio.run(_main(args))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
