# Document IA Infrastructure

This project contains shared code about infrastructure components for documentIA projects.

## Documentation

- [Redis Stream Consumer (`BaseConsumer`, `ThreadConsumer`, `AsyncIoConsumer`)](./docs/REDIS_CONSUMER.md) — architecture, execution modes, PEL recovery (`XAUTOCLAIM`), in-flight heartbeat (`XCLAIM JUSTID`), retries, idempotent DLQ, and lifecycle management.

## Environment Variables

### `WEBHOOK_SECRET_ENCRYPTION_KEY`

Webhook secret headers stored in PostgreSQL are encrypted at rest using [`cryptography.fernet.Fernet`](./src/document_ia_infra/service/webhook_encryption_service.py), which requires a 32-byte URL-safe base64-encoded key.

Both `document-ia-api` and `document-ia-worker` must share the **same** `WEBHOOK_SECRET_ENCRYPTION_KEY` value so that headers encrypted by the API can be decrypted by the worker.

Generate a valid key from the repository root with `uv`:

```bash
uv run --directory document-ia-infra python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Or using Python's standard library only (no virtual environment required):

```bash
python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Then set the generated value in your `.env` file (or deployment environment variables):

```dotenv
WEBHOOK_SECRET_ENCRYPTION_KEY=<generated-key>
```
