# Workflow Execution API

## Overview

The Workflow Execution API provides a robust endpoint for executing document processing workflows with file upload and metadata processing. This endpoint supports secure file uploads to S3/MinIO storage with comprehensive validation and error handling.

## Endpoint

```
POST /api/v1/workflows/{workflow_id}/execute
```

## Features

- **Authentication**: API Key authentication via `X-API-KEY` header
- **Rate Limiting**: Per-minute and per-day rate limits per API key
- **File Upload**: Multipart form data with robust file validation
- **S3 Storage**: Automatic file upload to S3/MinIO compatible storage
- **Metadata Processing**: JSON metadata object support
- **Error Handling**: Comprehensive error responses with detailed information

## Authentication

All requests require a valid API key in the `X-API-KEY` header:

```bash
X-API-KEY: your-api-key-here
```

## Rate Limiting

The endpoint enforces rate limiting:
- **Per-minute**: 300 requests per API key
- **Per-day**: 5000 requests per API key

Rate limit information is returned in response headers:
- `X-RateLimit-Remaining-Minute`
- `X-RateLimit-Remaining-Daily`
- `X-RateLimit-Reset-Minute`
- `X-RateLimit-Reset-Daily`

## File Requirements

### Supported Formats
- **PDF**: `application/pdf`
- **JPEG**: `image/jpeg`, `image/jpg`
- **PNG**: `image/png`

### File Size Limit
- **Maximum**: 25MB (26,214,400 bytes)

### File Validation
The API performs comprehensive file validation:
1. **Size Check**: Ensures file is within size limits
2. **Extension Validation**: Validates file extension
3. **MIME Type Detection**: Uses `python-magic` for content-based MIME type detection
4. **Cross-Validation**: Ensures extension matches detected MIME type
5. **Content Validation**: Validates file content integrity

## Request Format

### Content-Type
```
multipart/form-data
```

### Form Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | Document file to process |
| `metadata` | String | Yes | JSON string containing metadata object |

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `workflow_id` | String | Unique identifier for the workflow to execute |

## Request Example

### cURL
```bash
curl -X POST "https://api.example.com/api/v1/workflows/12345/execute" \
  -H "X-API-KEY: your-api-key-here" \
  -F "file=@document.pdf" \
  -F 'metadata={"$metadata": {"source": "email", "priority": "high", "tags": ["invoice", "urgent"]}}'
```

### Python (requests)
```python
import requests
import json

url = "https://api.example.com/api/v1/workflows/12345/execute"
headers = {"X-API-KEY": "your-api-key-here"}

metadata = {
    "$metadata": {
        "source": "email",
        "priority": "high",
        "tags": ["invoice", "urgent"],
        "user_id": "user123"
    }
}

files = {"file": open("document.pdf", "rb")}
data = {"metadata": json.dumps(metadata)}

response = requests.post(url, headers=headers, files=files, data=data)
print(response.json())
```

### JavaScript (fetch)
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('metadata', JSON.stringify({
  "$metadata": {
    "source": "email",
    "priority": "high",
    "tags": ["invoice", "urgent"]
  }
}));

fetch('/api/v1/workflows/12345/execute', {
  method: 'POST',
  headers: {
    'X-API-KEY': 'your-api-key-here'
  },
  body: formData
})
.then(response => response.json())
.then(data => console.log(data));
```

## Response Format

### Success Response (200 OK)

```json
{
  "status": "success",
  "data": {
    "execution_id": "exec_abc123def456",
    "workflow_id": "12345",
    "status": "processing",
    "created_at": "2024-01-15T10:30:00Z",
    "file_info": {
      "filename": "document.pdf",
      "size": 1024000,
      "content_type": "application/pdf",
      "file_id": "file_xyz789",
      "upload_timestamp": "2024-01-15T10:30:00Z"
    },
    "metadata": {
      "source": "email",
      "priority": "high",
      "tags": ["invoice", "urgent"]
    },
    "s3_info": {
      "s3_key": "uploads/2024/01/15/file_xyz789.pdf",
      "bucket_name": "document-ia",
      "presigned_url": "https://minio.example.com/presigned-url",
      "storage_class": "STANDARD"
    }
  },
  "message": "Workflow execution started successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Error Responses

#### 400 Bad Request - Validation Error
```json
{
  "status": "error",
  "error": "file_validation_error",
  "message": "File type 'text/plain' not supported. Supported types: application/pdf, image/jpeg, image/png",
  "details": {
    "filename": "document.txt",
    "size": 1024,
    "extension": ".txt",
    "content_type": "text/plain",
    "max_size_allowed": 26214400,
    "allowed_types": ["application/pdf", "image/jpeg", "image/png"]
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### 401 Unauthorized - Invalid API Key
```json
{
  "status": "error",
  "error": "unauthorized",
  "message": "Invalid API key",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### 404 Not Found - Workflow Not Found
```json
{
  "status": "error",
  "error": "workflow_not_found",
  "message": "Workflow with ID '12345' not found",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### 413 Payload Too Large - File Too Large
```json
{
  "status": "error",
  "error": "file_validation_error",
  "message": "File size exceeds maximum limit of 25MB",
  "details": {
    "filename": "large-document.pdf",
    "size": 31457280,
    "max_size_allowed": 26214400
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### 429 Too Many Requests - Rate Limit Exceeded
```json
{
  "status": "error",
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "rate_limit_info": {
    "limit_exceeded": true,
    "remaining_minute": 0,
    "remaining_daily": 45,
    "reset_minute": "2024-01-15T10:31:00Z",
    "reset_daily": "2024-01-16T00:00:00Z"
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### 500 Internal Server Error
```json
{
  "status": "error",
  "error": "internal_error",
  "message": "An internal server error occurred during workflow execution",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## S3 Storage

### File Organization
Files are stored in S3 with the following structure:
```
uploads/
├── YYYY/
│   ├── MM/
│   │   ├── DD/
│   │   │   ├── {file_id}.pdf
│   │   │   ├── {file_id}.jpg
│   │   │   └── {file_id}.png
```

### S3 Metadata
Each uploaded file includes metadata:
- `original-filename`: Original filename
- `content-type`: Detected MIME type
- `upload-timestamp`: ISO timestamp of upload
- `file-id`: Unique file identifier
- `workflow_metadata`: JSON string of workflow metadata
- `upload_source`: Source of upload (workflow_execution)

### Presigned URLs
The API generates presigned URLs for file access (valid for 1 hour).

## Error Handling

### File Validation Errors
- **Unsupported Format**: File type not in allowed list
- **File Too Large**: Exceeds 25MB limit
- **Invalid Content**: MIME type doesn't match extension
- **Corrupted File**: Unable to read file content

### Metadata Validation Errors
- **Invalid JSON**: Malformed JSON string
- **Empty Metadata**: Metadata object is empty
- **Missing Required Fields**: Required metadata fields missing

### S3 Upload Errors
- **Connection Failed**: Unable to connect to S3/MinIO
- **Bucket Not Found**: S3 bucket doesn't exist
- **Permission Denied**: Insufficient S3 permissions
- **Upload Failed**: General upload failure

## Security Considerations

### File Security
- **Content Validation**: Files are validated by content, not just extension
- **Size Limits**: Strict file size enforcement
- **MIME Type Detection**: Uses `python-magic` for accurate type detection
- **Path Traversal Protection**: Filenames are sanitized for S3 storage

### API Security
- **Authentication**: Required API key validation
- **Rate Limiting**: Prevents abuse and DoS attacks
- **Input Sanitization**: All inputs are validated and sanitized
- **Error Information**: Limited error details to prevent information leakage

## Monitoring and Logging

### Request Logging
- All requests are logged with sanitized data
- File uploads are tracked with unique identifiers
- Error conditions are logged with correlation IDs

### Performance Metrics
- File upload times
- S3 operation latencies
- Validation processing times
- Error rates by type

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENDPOINT_URL` | `http://localhost:9000` | S3/MinIO endpoint URL |
| `S3_ACCESS_KEY_ID` | `minioadmin` | S3 access key |
| `S3_SECRET_ACCESS_KEY` | `minioadmin` | S3 secret key |
| `S3_BUCKET_NAME` | `document-ia` | S3 bucket name |
| `S3_REGION_NAME` | `us-east-1` | S3 region |
| `S3_USE_SSL` | `false` | Use SSL for S3 connections |
| `MAX_FILE_SIZE` | `26214400` | Maximum file size in bytes (25MB) |

### Rate Limiting Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `300` | Requests per minute per API key |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `5000` | Requests per day per API key |

## Testing

### Running Tests
```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest tests/test_workflow_execution.py -v

# Run with coverage
poetry run pytest tests/test_workflow_execution.py --cov=src --cov-report=html
```

### Test Coverage
- File validation scenarios
- Authentication and authorization
- Rate limiting behavior
- S3 upload operations
- Error handling and responses
- Metadata validation

## Troubleshooting

### Common Issues

1. **File Upload Fails**
   - Check file size (must be ≤ 25MB)
   - Verify file format (PDF, JPG, PNG only)
   - Ensure file is not corrupted

2. **S3 Upload Errors**
   - Verify S3/MinIO is running
   - Check S3 credentials and permissions
   - Ensure bucket exists and is accessible

3. **Rate Limit Errors**
   - Check current usage against limits
   - Wait for rate limit reset
   - Consider upgrading rate limits if needed

4. **Authentication Errors**
   - Verify API key is correct
   - Check API key is included in `X-API-KEY` header
   - Ensure API key is not expired

### Debug Information
Enable debug logging by setting log level to DEBUG in the application configuration.

## Future Enhancements

- **Async Processing**: Background job processing with Redis
- **File Compression**: Automatic file compression for large uploads
- **Multi-file Support**: Support for multiple file uploads
- **Progress Tracking**: Real-time upload progress updates
- **File Versioning**: S3 object versioning support
- **Custom Workflows**: Dynamic workflow configuration

## Synchronous Execution

For lightweight workflows you can block until completion via:

```
POST /api/v1/workflows/{workflow_id}/execute-sync
```

This endpoint shares the same authentication, rate limiting and multipart payload as `/execute` but waits for the corresponding execution to finish (STARTED, SUCCESS, FAILED) or until a timeout occurs. The response body mirrors `GET /executions/{execution_id}` by returning the discriminated union `ExecutionResponse`.

### Timeouts & Polling

- Default timeout: `SYNC_EXECUTION_TIMEOUT_SECONDS` (30s) with a hard cap `SYNC_EXECUTION_MAX_WAIT_SECONDS` (60s).
- Poll interval: `SYNC_EXECUTION_POLL_INTERVAL_MS` (250ms) between Event Store checks.
- On timeout, the API returns **408** with an RFC-7807 payload containing `sync_execution_timeout`, the `execution_id`, and the last known status.

### Response Examples

#### 200 SUCCESS

```json
{
  "id": "exec_abc123",
  "status": "SUCCESS",
  "data": {
    "total_processing_time_ms": 840,
    "result": {
      "classification": {
        "document_type": "invoice",
        "confidence": 0.97
      },
      "extraction": null,
      "barcodes": []
    }
  }
}
```

#### 408 TIMEOUT

```json
{
  "type": "about:blank",
  "title": "Request Timeout",
  "status": 408,
  "code": "workflow.timeout",
  "detail": "Workflow execution did not finish before timeout",
  "errors": {
    "error": "sync_execution_timeout",
    "execution_id": "exec_abc123",
    "last_status": "STARTED"
  }
}
```

### Configuration

Add the following environment variables (defaults shown) to tune synchronous behaviour:

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNC_EXECUTION_TIMEOUT_SECONDS` | `30` | Soft timeout before returning 408 |
| `SYNC_EXECUTION_MAX_WAIT_SECONDS` | `60` | Absolute upper bound for blocking time |
| `SYNC_EXECUTION_POLL_INTERVAL_MS` | `250` | Delay between Event Store polls |
