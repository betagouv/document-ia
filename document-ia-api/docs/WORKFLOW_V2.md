# Workflow v2

v2 introduces YAML-defined workflows with runtime configuration resolution (defaults + overrides).

## Endpoints

- `GET /api/v2/workflows/`
- `POST /api/v2/workflows/{workflow_id}/execute`
- `POST /api/v2/workflows/{workflow_id}/execute-sync`

## Auth and authorization semantics

- `401 Unauthorized`: missing or invalid `X-API-KEY`.
- `403 Forbidden`: API key is valid but the resource is not accessible for the authenticated organization.

## 1) List available workflows

### Request

```http
GET /api/v2/workflows/
X-API-KEY: <your-key>
```

### Response (excerpt)

```json
{
  "status": "success",
  "data": [
    {
      "id": "document-extraction-v2",
      "name": "Document extraction v2 (Configurable)",
      "version": "2.0.0",
      "steps": [
        {"action": "download_file"},
        {
          "action": "llm_extract_data",
          "params": {
            "model": {
              "type": "string",
              "default": "openweight-medium",
              "enum": ["albert-small", "openweight-large", "openweight-medium", "openweight-small", "mistral-medium-2508"]
            }
          }
        }
      ]
    }
  ]
}
```

## 2) Start a v2 workflow (async)

### Request

`file` and `file_url` are mutually exclusive.

```bash
curl -X POST "/api/v2/workflows/document-extraction-v2/execute" \
  -H "X-API-KEY: <your-key>" \
  -F "file_url=https://example.com/document.pdf" \
  -F 'metadata={"source":"api","priority":"high"}'
```

### Response

Returns a `WorkflowV2ExecuteResponse` payload including:

- `execution_id`,
- `workflow_id`,
- `organization_id`,
- resolved `workflow_configuration` (steps + applied params).

## 3) Overrides (step-level customization)

The `override` field is a JSON object keyed by step action name.

### Simple example

```json
{
  "llm_extract_data": [
    {"param": "document_type", "value": "passeport"}
  ]
}
```

### Combined example

```json
{
  "llm_classify_document": [
    {"param": "document_types", "value": ["cni", "passeport"]}
  ],
  "llm_extract_data": [
    {"param": "model", "value": "albert-small"},
    {"param": "document_type", "value": "cni"}
  ]
}
```

### Validation rules

- step must exist in the workflow,
- parameter must be configurable for that step,
- value must match `type` / `enum` / `oneOf`,
- required params without defaults must be provided (YAML or override).

## 4) Start a v2 workflow synchronously

`execute-sync` is a wrapper around `execute`:

1. starts v2 execution (same validation and override resolution),
2. waits for terminal status (`SUCCESS` / `FAILED`) or timeout,
3. returns `ExecutionResponse`.

```bash
curl -X POST "/api/v2/workflows/document-extraction-v2/execute-sync" \
  -H "X-API-KEY: <your-key>" \
  -F "file_url=https://example.com/document.pdf" \
  -F 'override={"llm_extract_data":[{"param":"document_type","value":"passeport"}]}'
```

### Response example (`SUCCESS`)

```json
{
  "id": "exec-12345",
  "status": "SUCCESS",
  "data": {
    "total_processing_time_ms": 1250,
    "result": {
      "classification": {
        "document_type": "cni",
        "confidence": 0.98,
        "explanation": "Carte Nationale d'Identité française"
      },
      "extraction": {
        "type": "cni",
        "properties": [
          {
            "name": "nom",
            "type": "string",
            "value": "DUPONT"
          },
          {
            "name": "date_delivrance",
            "type": "date",
            "value": "2024-01-01"
          },
          {
            "name": "date_naissance",
            "type": "date",
            "value": null,
            "anomaly": {
              "code": "invalid_date",
              "raw_value": "31/04/2026"
            }
          }
        ]
      },
      "barcodes": []
    }
  }
}
```

> **Note sur les anomalies d'extraction (`anomaly`) :** lorsqu'une valeur candidate extraite est invalide (par exemple une date impossible sur le calendrier), `value` vaut `null` et l'objet `anomaly` contient le `code` d'erreur ainsi que la valeur brute `raw_value`. Pour les valeurs valides ou absentes sans anomalie, le champ `anomaly` est omis.

## Best practices

1. Start with `GET /api/v2/workflows/` to discover accepted parameters.
2. Keep overrides minimal and explicit.
3. Use `execute` (async) for long processing; reserve `execute-sync` for interactive use cases.
