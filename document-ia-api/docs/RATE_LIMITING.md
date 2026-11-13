# Rate Limiting

## Overview

The API applies **fixed-window rate limiting** per authenticated API key (not per IP address and not per organization).

- Minute window (starts at second `:00` of each UTC minute)
- Daily window (starts at `00:00:00` UTC each day)

> [!IMPORTANT]
> Rate limiting is enforced **strictly after successful API key authentication**.
> Unauthenticated or invalid API keys are rejected immediately (`401 Unauthorized`) without allocating, querying, or incrementing any rate limit quota in Redis.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `300` | Minute quota per authenticated API key |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `5000` | Daily quota per authenticated API key |

## Redis Storage & Privacy (Security Initiative #151 / Decision D5)

Redis keys are constructed using the key's internal database UUID (`api_key_dto.id`), **never** the sensitive API key secret string received in headers:

- Minute key: `rate_limit:minute:{key_id}:{YYYYMMDDHHMM}`
- Daily key: `rate_limit:daily:{key_id}:{YYYYMMDD}`

Where `{key_id}` is the canonical string representation of the key's internal UUID (e.g. `123e4567-e89b-12d3-a456-426614174000`).

### Benefits
1. **Zero Secret Leakage**: API secrets are never written to Redis keys, memory snapshots, slow logs, replication streams, or monitoring systems.
2. **Deterministic Shared Budgets**: Multiple valid representations or future alias formats of the same API key resolve to the identical internal UUID and therefore share the exact same quota.
3. **Key Isolation**: Quotas are scoped per individual API key; multiple API keys belonging to the same organization maintain independent budgets.

### TTL & Automatic Expiration
Counters expire automatically:
- Minute keys expire after 60 seconds (`TTL 60`).
- Daily keys expire after 86,400 seconds / 24 hours (`TTL 86400`).

Legacy keys containing raw key strings naturally age out within their TTL window without requiring complex backfills or data migrations.

## Response Headers

When applicable, the API returns the following rate limit headers on responses:

- `X-RateLimit-Remaining-Minute`: Remaining requests allowed in the current minute window.
- `X-RateLimit-Remaining-Daily`: Remaining requests allowed in the current daily window.
- `X-RateLimit-Reset-Minute`: ISO 8601 timestamp when the minute window resets.
- `X-RateLimit-Reset-Daily`: ISO 8601 timestamp when the daily window resets.

## Exceeded-Limit & Outage Responses

1. **Exceeded Quota (`429 Too Many Requests`)**:
   Returned when the request exceeds `RATE_LIMIT_REQUESTS_PER_MINUTE` or `RATE_LIMIT_REQUESTS_PER_DAY`.
   Includes a `Retry-After` header indicating the number of seconds until window reset. When multiple windows are exceeded, this value reflects `max(resets)` (the latest reset time among exhausted windows), ensuring the client does not retry until all exhausted windows have cleared.
   Requests rejected with `429 Too Many Requests` (e.g. when the minute quota is exceeded) do **not** increment or consume the daily quota counter, preserving the daily budget for subsequent valid requests.
2. **Redis Outage / Timeout (`503 Service Unavailable`)**:
   In accordance with the fail-closed policy introduced in PR #149, if Redis is down, unreachable, or times out during the quota check, the service raises `503 Service Unavailable` (`execution_capacity_unavailable`) with a bounded `Retry-After` header. Outages never fail open or grant uncounted capacity.
