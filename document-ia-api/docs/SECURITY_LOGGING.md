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

---

## 5. Operations: Historic Leak Auditing & Secret Rotation (Point 4)

To remediate historic exposures prior to the deployment of this PR, operators must search existing Loki logs for leaked credentials without disabling monitoring.

### 5.1 Grafana / Loki (LogQL) Audit Queries for Sandbox & Production

#### A. Comprehensive API Key Leak Discovery
Search for any Document IA generated API key pattern (`dia_<env>_<version>_<prefix>_<body>_<chk>`) across all logs:
```logql
{env="sandbox"} |= "dia_" |~ `dia_(dev|sandbox|staging|prod)_[0-9v]+_[A-Z0-9]{8}_[A-Z0-9]+_[A-Z0-9]{4}`
```

#### B. Targeted Search on Key Creation Endpoint (`aggregator` logs)
Inspect requests and responses on the API key creation route:
```logql
{app="document-ia-api", env="sandbox", logger="aggregator"}
  | json
  | normalized_path =~ ".*api-keys.*"
  |~ `dia_[a-zA-Z0-9_]+`
```

#### C. Extraction of Distinct Exposed Keys in Grafana Table
Extract the matched key into a temporary label `exposed_api_key` to build a list of keys requiring rotation:
```logql
{env="sandbox"}
  | regexp `(?P<exposed_api_key>dia_(sandbox|dev|staging|prod)_[a-zA-Z0-9_]{30,100})`
```
To calculate the occurrence count per exposed key:
```logql
sum by (exposed_api_key) (
  count_over_time({env="sandbox"} | regexp `(?P<exposed_api_key>dia_(sandbox|dev|staging|prod)_[a-zA-Z0-9_]{30,100})` [7d])
)
```

#### D. Webhook Tokens & Presigned URL Leaks
Scan for leaked custom authorization headers and presigned S3 signatures:
```logql
{app="document-ia-api", env="sandbox", logger="aggregator"}
  |= "webhooks"
  |~ `(?i)(bearer\s+[a-zA-Z0-9_\-\.]+|x-api-key)`
```
```logql
{env="sandbox"} |~ `(?i)(AWSAccessKeyId|X-Amz-Signature=[a-zA-Z0-9]+)`
```

### 5.2 SQL Queries for Organization Contacts & Key Rotation (Excluding Admin Keys)

Assuming historic leaks affected all standard tenant keys prior to this PR, run these queries to identify organizations and their respective contact emails:

#### A. Sandbox Environment
```sql
SELECT
    o.id AS organization_id,
    o.name AS organization_name,
    o.contact_email,
    k.id AS api_key_id,
    CONCAT('dia_sandbox_1_', k.prefix, '_***') AS masked_key,
    k.prefix,
    k.status,
    k.created_at
FROM organization o
JOIN api_key k ON k.organization_id = o.id
WHERE o.platform_role != 'PlatformAdmin'
ORDER BY o.name;
```

#### B. Production Environment
```sql
SELECT
    o.id AS organization_id,
    o.name AS organization_name,
    o.contact_email,
    k.id AS api_key_id,
    CONCAT('dia_prod_1_', k.prefix, '_***') AS masked_key,
    k.prefix,
    k.status,
    k.created_at
FROM organization o
JOIN api_key k ON k.organization_id = o.id
WHERE o.platform_role != 'PlatformAdmin'
ORDER BY o.name;
```

### 5.3 Communication Template for Tenant Representatives

```markdown
Objet : [Sécurité Document IA] Rotation requise de votre clé d'API ({{ masked_key }})

Bonjour,

Dans le cadre d'un audit de sécurité et de la mise à niveau de nos systèmes de journalisation (passage à une politique stricte d'interdiction de fuite de données), nous procédons par mesure de précaution à la rotation des clés d'accès à l'API Document IA.

Votre organisation **{{ organization_name }}** utilise actuellement la clé d'API débutant par **`{{ masked_key }}`**.

Afin de garantir la continuité de service et la sécurité de vos intégrations :
1. Une nouvelle clé d'API a été générée pour votre organisation dans votre espace d'administration.
2. Nous vous invitons à mettre à jour vos configurations d'intégration avec cette nouvelle clé dès réception.
3. L'ancienne clé débutant par **`{{ masked_key }}`** sera définitivement révoquée le **<DATE_A_DEFINIR>**.

L'équipe Document IA reste disponible pour tout échange ou accompagnement sur cette opération.
```

### 5.4 Remediation & Key Rotation Procedure
1. **Identify Exposed Keys**: Run Query 5.1.C or SQL Query 5.2.B over the operational retention window and export the list of unique `prefix` / `masked_key` values.
2. **Revoke Exposed Keys**:
   - Call `PATCH /api/v1/admin/api-keys/{id}/status` with `status: "REVOKED"` for each compromised key.
   - Generate a replacement key via `POST /api/v1/admin/organizations/{organization_id}/api-keys` and securely transmit the new credential to the affected tenant.
3. **Purge Compromised Log Segments**: Restrict access or execute Loki deletion requests for targeted chunks where secrets were detected, avoiding a full wipe of monitoring history.
