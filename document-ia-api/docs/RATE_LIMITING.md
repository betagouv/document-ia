# Rate Limiting

This document describes the rate limiting implementation for the Document IA API.

## Overview

The API implements rate limiting based on API keys to prevent abuse and ensure fair usage. Rate limits are enforced per API key, not per IP address.

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

Keys automatically expire after their respective time windows (60 seconds for minute, 86400 seconds for daily).

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
    "reset_minute": "2024-01-01T12:01:00",
    "reset_daily": "2024-01-02T00:00:00"
  }
}
```

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
