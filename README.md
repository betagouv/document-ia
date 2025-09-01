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
- **S3 Integration**: Async file storage operations
- **Idempotency**: All state-changing operations are idempotent
- **Multi-threading**: Thread-safe design with proper dependency injection
- **API Key Authentication**: Secure API access control

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

## Usage

### Development mode
```bash
poetry run dev
```

### Production mode
```bash
poetry run start
```

## API Endpoints

- **GET /** - Homepage with documentation links
- **GET /api/v1/** - API status (authentication required)
- **GET /api/health** - Health check (authentication required)
- **GET /docs** - Swagger UI documentation
- **GET /redoc** - ReDoc documentation
- **GET /openapi.json** - OpenAPI specification

## Authentication

All `/api/*` endpoints require authentication via the `X-API-KEY` header:

```bash
curl -H "X-API-KEY: YOUR_API_KEY" http://localhost:8000/api/v1/
```

**Note**: Authentication uses the `X-API-KEY` header, not Bearer token scheme.

## Environment Variables

### Required
- `API_KEY`: Authentication key required for API access
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `AWS_ACCESS_KEY_ID`: S3 access key
- `AWS_SECRET_ACCESS_KEY`: S3 secret key
- `AWS_REGION`: S3 region
- `S3_BUCKET_NAME`: S3 bucket name

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

### Code Quality
- Python 3.11+ features
- PEP 8 style guidelines
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