# Rate Limiting

This document describes the rate limiting implementation for the Document IA API.

## Overview

The API implements **fixed window rate limiting** based on API keys to prevent abuse and ensure fair usage. Rate limits are enforced per API key, not per IP address.

### Fixed Window Strategy

The rate limiting uses a **fixed window** approach, which means:

- **Minute Window**: Each minute (e.g., 13:30:00 - 13:30:59) has its own counter
- **Daily Window**: Each day (e.g., 2024-12-01 00:00:00 - 23:59:59) has its own counter
- **Reset Behavior**: Counters reset at the exact window boundary (e.g., 13:31:00 for minute, 00:00:00 for daily)
- **Consistency**: All requests within the same window share the same reset time

## Configuration

Rate limiting is configured through environment variables:

- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Maximum requests per minute (default: 300)
- `RATE_LIMIT_REQUESTS_PER_DAY`: Maximum requests per day (default: 5000)

## Implementation Details

### Architecture

The rate limiting follows Clean Architecture principles:

- **Infrastructure Layer**: `src/infra/redis_service.py` - Redis operations and connection management
- **Interface Layer**: `src/api/rate_limiting.py` - FastAPI dependencies and middleware
- **Configuration**: `src/infra/config.py` - Environment-based configuration

### Redis Storage

Rate limiting data is stored in Redis with the following key patterns:

- Minute limits: `rate_limit:minute:{api_key}:{YYYYMMDDHHMM}`
- Daily limits: `rate_limit:daily:{api_key}:{YYYYMMDD}`

**Key Generation Examples:**
- Request at `2024-12-01 13:30:45` → Minute key: `rate_limit:minute:api123:202412011330`
- Request at `2024-12-01 13:30:45` → Daily key: `rate_limit:daily:api123:20241201`

Keys automatically expire after their respective time windows (60 seconds for minute, 86400 seconds for daily).

### Reset Time Calculation

The reset times are calculated based on **window boundaries**, not request times:

```python
# Minute window reset calculation
minute_start = now.replace(second=0, microsecond=0)  # 13:30:45 → 13:30:00
next_minute = minute_start + timedelta(minutes=1)    # 13:30:00 → 13:31:00

# Daily window reset calculation
day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)  # 13:30:45 → 00:00:00
next_day = day_start + timedelta(days=1)                           # 00:00:00 → 00:00:00 next day
```

**Reset Time Examples:**
- Request at `13:30:45` → Minute resets at `13:31:00`, Daily resets at `00:00:00` next day
- Request at `13:59:30` → Minute resets at `14:00:00`, Daily resets at `00:00:00` next day
- Request at `23:59:45` → Minute resets at `00:00:00` next day, Daily resets at `00:00:00` next day

### Usage

Rate limiting is automatically applied to all `/api/v1/*` endpoints. To use rate limiting in your routes:

```python
from fastapi import Depends, Request
from api.rate_limiting import check_rate_limit

@router.get("/your-endpoint")
async def your_endpoint(
    request: Request,
    api_key: str = Depends(verify_api_key),
    rate_limit_info: dict = Depends(check_rate_limit)
):
    # Your endpoint logic here
    # Rate limit info is automatically stored in request.state.rate_limit_info
    return {"message": "Success"}
```

The rate limiting dependency automatically stores the rate limit information in `request.state.rate_limit_info`, which is then used by the middleware to add rate limit headers to the response.

### Response Headers

When rate limiting is active, the following headers are included in responses:

- `X-RateLimit-Remaining-Minute`: Remaining requests in the current minute
- `X-RateLimit-Remaining-Daily`: Remaining requests in the current day
- `X-RateLimit-Reset-Minute`: ISO timestamp when minute limit resets
- `X-RateLimit-Reset-Daily`: ISO timestamp when daily limit resets

**Example Response Headers:**
```
X-RateLimit-Remaining-Minute: 299
X-RateLimit-Remaining-Daily: 4999
X-RateLimit-Reset-Minute: 2024-12-01T13:31:00
X-RateLimit-Reset-Daily: 2024-12-02T00:00:00
```

**Header Interpretation:**
- `X-RateLimit-Reset-Minute: 2024-12-01T13:31:00` means the minute counter resets at 13:31:00 (not 1 minute from now)
- `X-RateLimit-Reset-Daily: 2024-12-02T00:00:00` means the daily counter resets at midnight (not 24 hours from now)

### Error Responses

When rate limits are exceeded, the API returns a `429 Too Many Requests` response:

```json
{
  "error": "Rate limit exceeded",
  "message": "Too many requests. Please try again later.",
  "rate_limit_info": {
    "limit_exceeded": true,
    "remaining_minute": 0,
    "remaining_daily": 0,
    "reset_minute": "2024-12-01T13:31:00",
    "reset_daily": "2024-12-02T00:00:00"
  }
}
```

**Error Response Example (Request at 13:30:45):**
- `reset_minute: "2024-12-01T13:31:00"` - Minute counter resets at 13:31:00 (15 seconds from request time)
- `reset_daily: "2024-12-02T00:00:00"` - Daily counter resets at midnight (10.5 hours from request time)

## Fixed Window vs Rolling Window

### Fixed Window Benefits
- **Predictable Reset Times**: Clients know exactly when limits reset
- **Simple Implementation**: Easy to understand and debug
- **Consistent Behavior**: All requests in same window share same reset time
- **Efficient Storage**: Uses simple counters instead of complex data structures

### Fixed Window Considerations
- **Burst Potential**: Allows bursts at window boundaries (e.g., 300 requests at 13:59:59 + 300 at 14:00:00)
- **Less Smooth**: Rate limiting is less smooth compared to rolling windows

**Client Action:**
- Wait until 13:31:00 to retry (not 1 minute from request time)
- Can make requests immediately after 13:31:00
- Daily limit still has 4699 requests remaining

## Fault Tolerance

The rate limiting system is designed to be fault-tolerant:

1. **Redis Unavailable**: If Redis is unavailable, requests are allowed but logged
2. **Connection Retry**: Automatic retry with exponential backoff for Redis connections
3. **Graceful Degradation**: Rate limiting is disabled when Redis is down, but the API continues to function

## Environment Setup

1. Set up Redis server
2. Configure environment variables (see `env.example`)
3. Install dependencies: `poetry install`
4. Start the API: `poetry run dev`
