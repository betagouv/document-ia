# API Summary

Entry point for API documentation.

## Table of contents

- [API Summary (this file)](./API_SUMMARY.md)
- [Architecture](./ARCHITECTURE.md)
- [Authentication](./AUTHENTICATION.md)
- [Error Handling](./ERROR_HANDLING.md)
- [Routes](./ROUTES.md)
- [Workflow v1 (Deprecated)](./WORKFLOW_V1_DEPRECATED.md)
- [Workflow v2](./WORKFLOW_V2.md)
- [Rate Limiting](./RATE_LIMITING.md)

## Quick navigation

1. **New project / onboarding**: start with [Architecture](./ARCHITECTURE.md), then [Authentication](./AUTHENTICATION.md).
2. **API consumption**: read [Routes](./ROUTES.md), then choose workflow docs:
   - [Workflow v2](./WORKFLOW_V2.md) (recommended),
   - [Workflow v1 (Deprecated)](./WORKFLOW_V1_DEPRECATED.md) (maintenance only).
3. **Error and quota behavior**:
   - [Error Handling](./ERROR_HANDLING.md),
   - [Rate Limiting](./RATE_LIMITING.md).

## Documentation conventions

- HTTP examples use relative URLs (`/api/...`) and `X-API-KEY`.
- Sync endpoints return an `ExecutionResponse` (`STARTED`/`SUCCESS`/`FAILED`).
- v1 is kept for compatibility, v2 is the target product version.
