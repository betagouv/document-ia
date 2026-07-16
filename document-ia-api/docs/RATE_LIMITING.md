# Rate Limiting

## Overview

The API applies **fixed-window rate limiting** per API key (not per IP).

- minute window,
- daily window.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `300` | minute quota per API key |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `5000` | daily quota per API key |

## Redis storage

Key patterns:

- `rate_limit:minute:{api_key}:{YYYYMMDDHHMM}`
- `rate_limit:daily:{api_key}:{YYYYMMDD}`

Keys expire automatically at the end of each window.

## Response headers

When applicable, the API returns:

- `X-RateLimit-Remaining-Minute`
- `X-RateLimit-Remaining-Daily`
- `X-RateLimit-Reset-Minute`
- `X-RateLimit-Reset-Daily`

## Exceeded-limit response

HTTP `429 Too Many Requests` with a detailed error payload.

## Operational notes

1. Resets are aligned to window boundaries (not rolling windows).
2. If Redis is unavailable, the system degrades defensively (API keeps responding, event is logged).
