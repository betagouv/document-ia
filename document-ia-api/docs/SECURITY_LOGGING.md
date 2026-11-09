# Safe by Default Logging Architecture (S2 Hardening)

This document specifies the logging security architecture and strict allowlist enforcement across Document IA (`document-ia-api`, `document-ia-worker`, and `document-ia-infra`), addressing issue **#153 (S2)**.

---

## 1. Threat Model & Principles

Prior to this hardening, Document IA relied on opportunistic field masking (`x-mask`) coupled with a raw payload fallback (`body[:4096].decode()`). This approach suffered from structural leak vectors:
- **Malformed or non-JSON payloads**: Any invalid JSON syntax bypassed schema validation and triggered the raw body fallback, directly dumping secrets, passwords, or document fragments into aggregation logs.
- **Unannotated contracts**: Endpoints returning newly minted credentials (e.g. `APIKeyCreatedResult.key`) or webhook custom headers logged unmasked values in response previews.
- **Presigned URLs & S3 keys**: Downloader components logged full remote URLs containing presigned tokens and AWS query parameters.
- **Worker document extraction prompts**: `StepLLMMetadata` serialized the full `user_prompt` (containing the OCR text extracted from user documents) into Loki aggregator logs.

### Core Architectural Principle: Safe by Design via Allowlist
Document IA enforces a strict positive allowlist approach:
1. **Zero Raw Body Previews**: `request_body_preview` and `response_body_preview` are eliminated. Logs record only non-sensitive envelope metadata (`content_type`, `bytes`).
2. **Strict Parameter Allowlists**: Only explicitly whitelisted request headers, response headers, query parameters, and path parameters are serialized into log records. Any unknown or custom header/parameter is pruned or masked.
3. **Zero Complete URLs**: Full remote URLs, S3 presigned URLs, and webhook URLs are forbidden in application logs. Only the target hostname (`domain` / `host`) and technical correlation IDs are emitted.
4. **Purged Worker Metadata**: LLM and OCR task metadata logged to Loki is filtered through an allowlist, permanently stripping document contents (`user_prompt`, `system_prompt`, `output_images`).
5. **Contract Protection**: Private API keys and secret dictionaries use `SecretPayloadStr` and `SecretPayloadDict`, ensuring automatic masking (`**********`) across logs while preserving valid plaintext payload delivery to authorized HTTP clients.

---

## 2. API Logging Allowlist Specifications

### 2.1 Request Headers Allowlist (`ALLOWED_REQUEST_HEADERS`)
Only standard, non-sensitive HTTP headers are retained in API logs:
```python
ALLOWED_REQUEST_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "user-agent",
        "accept",
        "accept-encoding",
        "host",
        "x-request-id",
    }
)
```
> [!IMPORTANT]
> All other headers—including `Authorization`, `Cookie`, `X-Api-Key`, `X-Signature`, and custom bearer headers—are strictly discarded before log entry construction.

### 2.2 Response Headers Allowlist (`ALLOWED_RESPONSE_HEADERS`)
```python
ALLOWED_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "x-request-id",
        "idempotent-replay",  # Preshot to support seamless integration with idempotency key feature (#148)
        "location",
    }
)
```

### 2.3 Query Parameters Allowlist (`ALLOWED_QUERY_PARAMS`)
```python
ALLOWED_QUERY_PARAMS = frozenset(
    {
        "limit",
        "offset",
        "page",
        "status",
        "sort",
        "order",
        "direction",
        "workflow_id",
        "execution_id",
    }
)
```
*Any query parameter not included in this allowlist is replaced by `"**********"`.*

### 2.4 Path Parameters Allowlist (`ALLOWED_PATH_PARAMS`)
```python
ALLOWED_PATH_PARAMS = frozenset(
    {
        "execution_id",
        "organization_id",
        "workflow_id",
        "webhook_id",
        "task_id",
        "version",
    }
)
```

### 2.5 Request & Response Body Metadata
Instead of raw body strings or recursively dumped models, logs record structured envelope metrics:
```json
{
  "request_body": {
    "content_type": "application/json",
    "bytes": 248
  },
  "response_body": {
    "content_type": "application/json",
    "bytes": 104
  }
}
```

---

## 3. Remote URLs and Webhook Security

### 3.1 Downloader URL Logging (`DownloadFileStep`)
Logging complete URLs poses severe risks when presigned S3 URLs or authenticated endpoints are consumed. The worker must sanitize log records by:
- Emitting only the network location: `host = urlparse(file_url).netloc`
- Never logging `file_info.s3_key`
- Sanitizing network exceptions: only `exception_class`, `status_code`, and `elapsed_seconds` are logged, without embedding raw exception messages that might echo query strings.

### 3.2 Webhook Logging (`WebhookNotificationService`)
- Outgoing webhook notifications log solely the target hostname and correlation IDs:
  ```text
  Sending webhook notification to host example.com (webhook_id=..., execution_id=...)
  ```
- Custom webhook headers stored in database are typed with `SecretPayloadDict` to prevent disclosure.
- In case of HTTP failures (4xx/5xx), neither the remote URL query string nor the remote error response body is logged.

---

## 4. Worker Task Metadata Allowlist

In `handle_finish_execution`, execution metadata reported to Loki is strictly filtered through `ALLOWED_STEP_METADATA_FIELDS`:

```python
ALLOWED_STEP_METADATA_FIELDS = frozenset(
    {
        "step_name",
        "execution_time",
        "request_tokens",
        "response_tokens",
        "model",
    }
)
```

Fields explicitly excluded and scrubbed:
- `user_prompt`: contains raw OCR text extracted from personal documents (CNI, payslips, tax assessments, etc.).
- `system_prompt`: internal instructions and business rules.
- `output_images`: visual artifacts.
