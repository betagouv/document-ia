# Document IA Backend

This project will include a FastAPI backend (Readme: document-ia-api/README.md)
This project will also include a worker service to process messages from Redis queue

## Project Structure

```
document-ia-api/
├── src/
├── tests/                          # Unit and integration tests
├── pyproject.toml                  # Poetry configuration
└── poetry.lock                     # Dependency lock file
document-ia-worker/
├── src/
├── tests/                          # Unit and integration tests
├── pyproject.toml                  # Poetry configuration
└── poetry.lock                     # Dependency lock file
docker-compose.yml                 # Docker Compose file for local development
.env
```

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

The `docker-compose.yml` file uses environment variables from your `.env` file. Make sure your `.env` file includes the
following variables (see `env.example` for reference):

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

These variables are used by Docker Compose to configure the PostgreSQL, Redis, and MinIO services. The application will
connect to these services using the same configuration.

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

3. **To make changes on the api without having to bump the version code**
```bash
# This will create a symlink to the infra package
poetry run pip install -e ../document-ia-infra
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
