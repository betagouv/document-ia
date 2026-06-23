# Authentication

## Mechanism

The API uses an API key sent in the header:

```http
X-API-KEY: dia_<env>_v<version>_<prefix>_<body>_<checksum>
```

The FastAPI security scheme is defined in `api/auth.py` through `APIKeyHeader(name="X-API-KEY")`.

## Behavior

1. Read key from `X-API-KEY`.
2. Resolve key in DB (`ApiKeyService`).
3. Verify linked organization.
4. Inject organization in `request.state.organization`.

If key is missing, invalid, or not linked:

- `401 Unauthorized`.

## Admin checks

Admin routes require `is_platform_admin`:

- key must be valid,
- organization must have role `PlatformAdmin`.

Otherwise:

- `403 Forbidden` (authenticated but not enough privileges).

## Related endpoints

- **Most business routes** require `X-API-KEY`.
- Some health routes may stay public depending on router setup.

See [Routes](./ROUTES.md) for endpoint-by-endpoint details.
