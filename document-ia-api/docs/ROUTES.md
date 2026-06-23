# Routes

## Base path

- API is mounted under `/api`
- Exposed versions:
  - `/api/v1`
  - `/api/v2`

## Endpoint index

### Global

- `GET /api/test`

### v1

- `POST /api/v1/workflows/{workflow_id}/execute`
- `POST /api/v1/workflows/{workflow_id}/execute-sync`
- `GET /api/v1/executions/{execution_id}`
- `GET /api/v1/health`
- `GET /api/v1/extraction-schemas`

#### v1 admin

- `GET /api/v1/admin/organizations`
- `GET /api/v1/admin/organizations/{organization_id}`
- `POST /api/v1/admin/organizations`
- `DELETE /api/v1/admin/organizations/{organization_id}`
- `POST /api/v1/admin/organizations/{organization_id}/api-keys`
- `PUT /api/v1/admin/api-keys/{api_key_id}`
- `DELETE /api/v1/admin/api-keys/{api_key_id}`
- `GET /api/v1/admin/organizations/{organization_id}/webhooks`
- `POST /api/v1/admin/organizations/{organization_id}/webhooks`
- `DELETE /api/v1/admin/webhooks/{webhook_id}`

### v2

- `GET /api/v2/workflows/` (list available v2 workflows)
- `POST /api/v2/workflows/{workflow_id}/execute`
- `POST /api/v2/workflows/{workflow_id}/execute-sync`

## Interactive documentation

- Swagger: `/docs`
- ReDoc: `/redoc`

## Migration guidance

- New integrations should prefer **v2**.
- **v1** remains available but is considered legacy (see [Workflow v1 (Deprecated)](./WORKFLOW_V1_DEPRECATED.md)).
