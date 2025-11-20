# Document IA API

A FastAPI-based document analysis API following Clean Architecture principles with PostgreSQL, Redis, and S3 integration.

## Architecture Overview

This project implements Clean Architecture with dependency injection for external interfaces:

- **Domain Layer** (`core/`): Core  business logic independent of external frameworks
- **Application Layer** (`application/`): Use cases and orchestration logic
- **Infrastructure Layer** (`infra/`): External interfaces (DB, Redis, S3) implementations
- **Interface Layer** (`api/`): API routes and controllers

## Project Structure

```
document-ia-api/
├── src/
│   ├── __init__.py
│   ├── main.py                      # FastAPI application entry point
│   ├── api/                         # Interface layer (routes, controllers)
│   │   ├── __init__.py
│   │   ├── exceptions/             # API exceptions
│   │   ├── auth.py                 # Authentication logic
│   │   ├── config.py               # Configuration management
│   │   └── routes.py               # API routes
│   ├── application/                 # Application layer (use cases, services)
│   │   ├── __init__.py
│   │   └── services/               # Application services
│   ├── core/                        # Domain layer (business logic, entities)
│   │   ├── __init__.py
│   │   ├── config.py               # Configuration management
│   │   └── exceptions/             # Domain exceptions
│   ├── infra/                      # Infrastructure layer (DB, Redis, S3 adapters)
│   │   ├── __init__.py
│   │   ├── database/               # Database adapters and repositories
│   │   ├── cache/                  # Redis caching adapters
│   │   ├── storage/                # S3 storage adapters
│   │   └── messaging/              # Redis messaging adapters
│   ├── middleware/                  # FastAPI middleware
│   ├── models/                      # SQLAlchemy models
│   └── schemas/                     # Pydantic schemas
├── tests/                          # Unit and integration tests
├── pyproject.toml                  # Poetry configuration
└── poetry.lock                     # Dependency lock file
```

## Key Features

- **Clean Architecture**: Separation of concerns with dependency injection
- **Async/await**: All external operations (DB, Redis, S3) are asynchronous
- **PostgreSQL**: SQLAlchemy 2.0+ with async support and connection pooling
- **Redis**: Caching and message queuing with robust reconnection policies
- **MinIO Integration**: S3-compatible async file storage operations
- **Idempotency**: All state-changing operations are idempotent
- **Multi-threading**: Thread-safe design with proper dependency injection
- **API Key Authentication**: Secure API access control
- **Rate Limiting**: API key-based rate limiting with Redis storage

## Installation

1. **Install Poetry** (if not already installed)
```bash
pipx install poetry
```

2. **Install dependencies**
```bash
poetry install
```

3**Install system dependencies**
macos :
```bash
brew install libmagic
```

3. **Configure environment**
```bash
cp env.example .env
# Edit .env and set your configuration values
```

## Database, Redis & MinIO Setup

The FastAPI application requires PostgreSQL, Redis, and MinIO (S3 compatible storage) instances to function properly. You can use the provided `docker-compose.yml` file to quickly set up these services locally.

### Using Docker Compose

1. **Start the services**
```bash
# Start PostgreSQL and Redis in detached mode
docker-compose up -d
```

2. **Stop the services**
```bash
# Stop and remove containers
docker-compose down
```

3. **View service logs**
```bash
# View all service logs
docker-compose logs

# View specific service logs
docker-compose logs postgres
docker-compose logs redis
docker-compose logs minio

# Follow logs in real-time
docker-compose logs -f
```

4. **Check service status**
```bash
# List running containers
docker-compose ps

# Check service health
docker-compose exec postgres pg_isready
docker-compose exec redis redis-cli ping
docker-compose exec minio mc admin info local
```

### Environment Variables

The `docker-compose.yml` file uses environment variables from your `.env` file. Make sure your `.env` file includes the following variables (see `env.example` for reference):

```bash
# PostgreSQL Configuration
POSTGRES_DB=document_ia
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-postgres-password
POSTGRES_PORT=5432

# Redis Configuration
REDIS_PORT=6379

# MinIO Configuration (S3 compatible)
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_API_PORT=9000
MINIO_CONSOLE_PORT=9001
```

These variables are used by Docker Compose to configure the PostgreSQL, Redis, and MinIO services. The application will connect to these services using the same configuration.

### MinIO Access

MinIO provides S3-compatible object storage with a web-based management console:

- **API Endpoint**: `http://localhost:9000` (or the port specified in `MINIO_API_PORT`)
- **Web Console**: `http://localhost:9001` (or the port specified in `MINIO_CONSOLE_PORT`)

#### Initialize MinIO Bucket

Before using the application, you need to create the default S3 bucket. Use the provided initialization script:

```bash
# Run the MinIO bucket initialization script
python scripts/init-s3-bucket.py
```

This script will:
- Connect to your MinIO instance
- Create the default bucket (`document-ia`) if it doesn't exist
- Verify the bucket is accessible

**Note**: Make sure your MinIO service is running (`docker-compose up -d`) before running this script.

#### Accessing MinIO Console

1. Start the services: `docker-compose up -d`
2. Open your browser and navigate to `http://localhost:9001`
3. Login with the default credentials (or those specified in your `.env` file)
4. Create buckets and manage your S3-compatible storage

#### Using MinIO with S3 SDK

MinIO is fully compatible with AWS S3 SDKs. Configure your application to use MinIO instead of AWS S3:

```python
# Example configuration for MinIO
S3_ENDPOINT_URL = "http://localhost:9000"
S3_ACCESS_KEY = "minioadmin"
S3_SECRET_KEY = "minioadmin"
S3_REGION = "us-east-1"  # MinIO default region
```

## Usage

### Development mode
```bash
poetry run dev
```

## API Endpoints

- **GET /** - Homepage with documentation links
- **GET /api/v1/** - API status (authentication required)
- **GET /api/v1/health** - Health check (authentication required)
- **GET /docs** - Swagger UI documentation
- **GET /redoc** - ReDoc documentation
- **GET /openapi.json** - OpenAPI specification

## Authentication

All `/api/*` endpoints require authentication via the `X-API-KEY` header:

```bash
curl -H "X-API-KEY: YOUR_API_KEY" http://localhost:8000/api/v1/
```

**Note**: Authentication uses the `X-API-KEY` header, not Bearer token scheme.

## Rate Limiting

The API implements rate limiting based on API keys to prevent abuse and ensure fair usage. Rate limits are enforced per API key, not per IP address.

### Configuration

Rate limiting is configured through environment variables:

- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Maximum requests per minute (default: 300)
- `RATE_LIMIT_REQUESTS_PER_DAY`: Maximum requests per day (default: 5000)

### Usage

Rate limiting is automatically applied to all `/api/v1/*` endpoints. When rate limits are exceeded, the API returns a `429 Too Many Requests` response.

### Response Headers

Rate limiting information is included in response headers:

- `X-RateLimit-Remaining-Minute`: Remaining requests in the current minute
- `X-RateLimit-Remaining-Daily`: Remaining requests in the current day
- `X-RateLimit-Reset-Minute`: ISO timestamp when minute limit resets
- `X-RateLimit-Reset-Daily`: ISO timestamp when daily limit resets

For detailed documentation, see [RATE_LIMITING.md](RATE_LIMITING.md).

## Environment Variables

### Required
- `API_KEY`: Authentication key required for API access
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `MINIO_ROOT_USER`: MinIO root user
- `MINIO_ROOT_PASSWORD`: MinIO root password
- `MINIO_API_PORT`: MinIO API port (default: 9000)
- `MINIO_CONSOLE_PORT`: MinIO console port (default: 9001)

### Optional
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `LOG_LEVEL`: Logging level (default: INFO)

## Core Dependencies

- **FastAPI**: Modern, fast web framework
- **Uvicorn**: ASGI server for FastAPI
- **SQLAlchemy 2.0+**: Async ORM with connection pooling
- **Redis**: Async Redis client for caching and messaging
- **Boto3**: AWS SDK for S3 operations
- **Pydantic**: Data validation and serialization
- **Pydantic-settings**: Configuration management

## Architecture Principles

### Clean Architecture Implementation
- **External Dependencies**: Database, caching, messaging, and file storage are injected as dependencies
- **Domain Layer**: Core business logic is independent of external frameworks
- **Application Layer**: Use cases and orchestration logic
- **Infrastructure Layer**: External interfaces (DB, Redis, S3) implementations
- **Interface Layer**: API routes and controllers

### Async Operations
- All external calls (PostgreSQL, Redis, S3) are asynchronous
- Proper connection pooling for all external services
- Robust error handling with exponential backoff for Redis connections

### Idempotency
- HTTP request idempotency using idempotency keys
- Background task idempotency with unique task IDs
- Proper deduplication logic and audit logging

### Thread Safety
- Thread-safe data structures
- Dependency injection for shared resources
- Async/await patterns to avoid blocking operations

## Development Guidelines

### Code Quality & Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality. The setup includes:

- **Ruff**: Fast Python linter and formatter
- **Pre-commit hooks**: Automated checks before commits

#### Setup Pre-commit Hooks

1. **Install dependencies** (if not already done):
```bash
poetry install
```

2. **Install pre-commit hooks**:
```bash
# Manual installation
pre-commit install
```

#### Code Quality Standards
- Python 3.11+ features
- PEP 8 style guidelines (enforced by ruff)
- Type hints for all function parameters and return values
- Comprehensive error handling with custom exceptions
- Structured logging with data sanitization

### Testing
- Unit tests for all business logic
- Integration tests for external dependencies
- Async test support
- Mock external services in tests
- Test idempotency behavior

### Security
- Proper authentication and authorization
- Input sanitization
- Rate limiting
- HTTPS in production
- File upload validation

## Deployment

The project is configured for production deployment on Heroku with:
- Procfile for process management
- Heroku Postgres and Redis add-ons
- Environment variable configuration
- Proper logging for Heroku

## Performance & Monitoring

- Connection pooling for all external services
- Caching strategies with Redis
- Performance metrics logging
- Health checks implementation
- Structured logging for easy analysis

## Contributing

1. Follow Clean Architecture principles
2. Use async/await for all I/O operations
3. Implement proper error handling
4. Write comprehensive tests
5. Use type hints
6. Sanitize data before logging
7. Make operations idempotent

## License

[License information here]

## Aggregator middleware masking (x-mask)

To prevent sensitive data from leaking into logs, the aggregator middleware supports masking fields declared in Pydantic models using a vendor extension.

- Mark any Pydantic field you want to mask in logs with:
  - `Field(..., json_schema_extra={"x-mask": True})`
- At log time only, values of fields with `x-mask: True` are replaced by `"***"`.
- If the value is `None`, it is not masked (kept as `null`).
- This does not affect your OpenAPI schema or runtime responses; masking applies only to request/response previews emitted by the aggregator.

Example:

```python
from pydantic import BaseModel, Field

class ExtractionProperty(BaseModel):
    name: str
    value: str | float | int | bool | None = Field(
        json_schema_extra={"x-mask": True}
    )
```

Notes:
- Masking is recursive for nested Pydantic models and lists. If a field is a model or list of models, the aggregator walks the schema and applies `x-mask` to any nested fields where it’s set.
- For query/path/form parameters, existing secret types (e.g. SecretPayloadStr/Bytes) remain supported and are masked as before.
- Only small JSON bodies are parsed and masked (up to 4096 bytes) to keep logging safe and efficient.

## API Error Handling (Problem Details)

All API errors are returned as a structured JSON response following the Problem Details (RFC 7807) conventions. This ensures consistent error shapes across the API and makes it easier for clients to handle failures in a predictable way.

Payload shape (ProblemDetail):
- type: RFC7807 type URI (default: "about:blank")
- title: Short, human-readable summary of the problem
- status: HTTP status code
- detail: Optional human-readable detail (short string)
- instance: Request path
- code: Stable application-level error code (for programmatic handling)
- trace_id: Correlation ID to find the request in the logs (set by aggregator middleware)
- errors: Optional dictionary with structured error data (field -> messages or additional objects)

Error mappings
- 422 Validation failed (Request body/query/path validation)
  - title: "Validation failed"
  - code: "validation.failed"
  - errors: { "__root__": fastapi.exc.errors() }
- Starlette/FastAPI HTTP exceptions (HTTPException)
  - 400 -> code: "http.validation_error" (or specific content if detail is a dict)
  - 401 -> code: "http.unauthorized"
  - 403 -> code: "http.forbidden"
  - 404 -> code: "http.not_found"
  - 405 -> code: "http.method_not_allowed"
  - 413 -> code: "http.payload_too_large"
  - 429 -> code: "http.rate_limited"
  - other -> code: "http.error"
  - If the HTTPException.detail is a dict, it will be placed under ProblemDetail.errors.
- AppError (domain/application errors)
  - Raise AppError(status=..., title=..., code=..., errors=...) to return a custom ProblemDetail.
  - Example usage: health check returns 503 with detailed dependency status.
- Unhandled exceptions
  - 500 Internal Server Error
  - code: "internal.error"

Examples
- 401 Unauthorized
  {
    "type": "about:blank",
    "title": "Unauthorized",
    "status": 401,
    "code": "http.unauthorized",
    "detail": "Unauthorized",
    "instance": "/api/v1/resource"
  }

- 404 Not Found
  {
    "type": "about:blank",
    "title": "Not Found",
    "status": 404,
    "code": "http.not_found",
    "instance": "/api/v1/executions/exec_123",
    "errors": { "entity": "Execution", "id": "exec_123", "message": "Execution not found" }
  }

- 429 Too Many Requests
  {
    "type": "about:blank",
    "title": "Too Many Requests",
    "status": 429,
    "code": "http.rate_limited",
    "detail": "Rate limit exceeded. Please try again later.",
    "instance": "/api/v1/workflows/{workflow_id}/execute"
  }

- 500 Internal Server Error
  {
    "type": "about:blank",
    "title": "Internal Server Error",
    "status": 500,
    "code": "internal.error",
    "instance": "/api/v1/executions/exec_123",
    "trace_id": "3e4f4b2a-1c2d-4ef8-9a0b-123456789abc"
  }

- 503 Service Unavailable (health)
  {
    "type": "about:blank",
    "title": "Service Unavailable",
    "status": 503,
    "code": "health_check.unhealthy",
    "instance": "/api/v1/health",
    "errors": {
      "s3": {"connected": false, "credentials_valid": false, "bucket_exists": false, "is_healthy": false, "errors": ["S3 connection failed"]},
      "redis": {"connected": false, "is_healthy": false, "errors": ["Redis connection failed"]},
      "database": {"connected": false, "is_healthy": false, "errors": ["Database connection failed"]}
    }
  }

- 400 Bad Request (file validation example)
  If a service raises HTTPException with a dict detail, the dict is mapped into ProblemDetail.errors:
  {
    "type": "about:blank",
    "title": "Bad Request",
    "status": 400,
    "code": "http.validation_error",
    "instance": "/api/v1/workflows/{workflow_id}/execute",
    "errors": {
      "error": "file_validation_error",
      "message": "Invalid file format. Supported formats: PDF, JPG, PNG",
      "file_info": {"filename": "document.txt", "size": 1024, "content_type": "text/plain"}
    }
  }

Developer guidelines
- Prefer raising AppError for domain-level failures where you control the title/code and want to return structured `errors`.
- For request-specific 400 errors, raise HTTPException with a dict `detail`; it will be exposed under ProblemDetail.errors.
- Do not raise raw strings for complex errors; put machine-readable fields under `errors`.
- Always log with the `trace_id` (available in ProblemDetail) for correlation.

Consumer guidelines
- Inspect `code` to branch logic programmatically (e.g., http.unauthorized, http.rate_limited, validation.failed).
- Use `errors` for structured details (validation errors, domain-specific fields).
- Use `trace_id` to correlate with server logs when reporting incidents.
