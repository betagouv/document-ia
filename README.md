# Document IA API

A FastAPI-based document analysis API following Clean Architecture principles with PostgreSQL, Redis, and S3 integration.

## Architecture Overview

This project implements Clean Architecture with dependency injection for external interfaces:

- **Domain Layer** (`core/`): Core business logic independent of external frameworks
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
