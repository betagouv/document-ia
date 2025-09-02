# Document IA API Tests

This directory contains integration and unit tests for the Document IA API.

## Test Structure

```
tests/
├── __init__.py                 # Makes tests a Python package
├── conftest.py                 # Pytest configuration and fixtures
├── pytest.ini                 # Pytest configuration file
├── test_rate_limiting.py      # Rate limiting tests
├── api/                        # API layer tests
│   ├── __init__.py
│   ├── test_api_authentication.py  # API authentication tests
│   └── test_workflow_execution.py  # Workflow execution API tests
├── integration/                # Integration tests
│   ├── __init__.py
│   └── test_s3_service.py     # S3 service integration tests
├── unit/                       # Unit tests
│   ├── __init__.py
│   └── test_file_validator.py # File validator unit tests
└── README.md
```

## Running Tests

### Using pytest directly

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/api/test_api_authentication.py

# Run all API tests
pytest tests/api/

# Run all integration tests
pytest tests/integration/

# Run all unit tests
pytest tests/unit/

# Run specific test class
pytest tests/api/test_api_authentication.py::TestAPIAuthentication

# Run specific test method
pytest tests/api/test_api_authentication.py::TestAPIAuthentication::test_valid_api_key_returns_200
```

### Using Poetry

```bash
# Install dependencies first
poetry install

# Run tests
poetry run pytest
```

## Test Categories

### Test Organization

Tests are organized into three main categories:

- **`api/`**: Tests for API endpoints, authentication, and request/response handling
- **`integration/`**: Tests that verify integration with external services (S3, Redis, etc.)
- **`unit/`**: Tests for individual components and business logic in isolation

### Test Patterns

The tests follow these patterns:

1. **Arrange-Act-Assert**: Clear separation of test setup, execution, and verification
2. **Descriptive Names**: Test method names clearly describe what is being tested
3. **Comprehensive Coverage**: Tests cover happy path, error cases, and edge cases
4. **Isolation**: Each test is independent and doesn't rely on other tests
5. **Fixtures**: Common setup is extracted into reusable fixtures

## Adding New Tests

When adding new tests:

1. **Choose the right directory**:
   - `api/` for API endpoint tests
   - `integration/` for external service integration tests
   - `unit/` for isolated component tests
2. Create a new test file following the naming convention `test_*.py`
3. Use descriptive class and method names
4. Add appropriate docstrings explaining what each test validates
5. Use fixtures from `conftest.py` for common setup
6. Follow the Arrange-Act-Assert pattern
7. Include both positive and negative test cases

## Test Dependencies

The tests require these additional dependencies (already added to pyproject.toml):

- `pytest`: Test framework
- `pytest-asyncio`: Async test support
- `httpx`: HTTP client for testing FastAPI applications

## Configuration

The test configuration is set up in:

- `conftest.py`: Pytest fixtures and configuration
- `pytest.ini`: Pytest command-line options and markers

## Best Practices

1. **Mock External Dependencies**: Use mocking to isolate the code under test
2. **Test Error Cases**: Always test both success and failure scenarios
3. **Use Descriptive Assertions**: Make test failures easy to understand
4. **Keep Tests Fast**: Avoid slow operations in unit tests
5. **Test Edge Cases**: Include boundary conditions and unusual inputs
6. **Maintain Test Data**: Use fixtures to manage test data consistently
