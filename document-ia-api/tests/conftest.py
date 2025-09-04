"""
Pytest configuration and fixtures for Document IA API tests.

This module provides common fixtures and configuration for all integration tests.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv

# Add the src directory to Python path for imports
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.rate_limiting import RateLimitMiddleware
from api.routes import router
from schemas.rate_limiting import RateLimitInfo

# Load test environment variables
test_env_path = os.path.join(os.path.dirname(__file__), ".env.test")
if os.path.exists(test_env_path):
    load_dotenv(test_env_path)


def create_test_app(api_key: str = None):
    """
    Create a FastAPI test application with controlled settings.

    Args:
        api_key: The API key to use for testing

    Returns:
        FastAPI: A test application instance
    """

    # Create test settings
    class TestSettings:
        APP_VERSION = "1.0.0-test"
        API_KEY = api_key

    # TODO: Do not copy and paste the app configuration from the main.py file
    # Create FastAPI application
    app = FastAPI(title="API Document IA - Test")

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RateLimitMiddleware)

    # Override the settings in auth module
    import api.auth

    api.auth.settings = TestSettings()

    # Include API routes
    app.include_router(router, prefix="/api", tags=["API"])

    return app


@pytest.fixture
def mock_redis_service():
    """
    Create a mock Redis service for testing.

    This avoids actual Redis connections during tests.

    Returns:
        MagicMock: A mocked Redis service
    """
    mock_service = MagicMock()

    # Mock the check_rate_limit method to return success
    mock_service.check_rate_limit = AsyncMock(
        return_value=(
            True,  # is_allowed
            RateLimitInfo(
                limit_exceeded=False,
                remaining_minute=99,
                remaining_daily=999,
                reset_minute="2024-01-01T12:01:00",
                reset_daily="2024-01-02T00:00:00",
            ),
        )
    )

    return mock_service


@pytest.fixture
def valid_api_key():
    """
    Provide a valid API key for testing.

    Returns:
        str: A valid API key for authentication
    """
    return "test-api-key-12345"


@pytest.fixture
def client_with_api_key(valid_api_key, mock_redis_service):
    """
    Create a test client with a valid API key configured.

    Args:
        valid_api_key: The valid API key to use in settings
        mock_redis_service: Mocked Redis service

    Returns:
        TestClient: A test client with API key configured
    """
    # Patch the redis_service with our mock
    import api.rate_limiting

    original_redis_service = api.rate_limiting.redis_service
    api.rate_limiting.redis_service = mock_redis_service

    client = TestClient(create_test_app(api_key=valid_api_key))

    # Restore original service after test
    yield client

    api.rate_limiting.redis_service = original_redis_service


@pytest.fixture
def client_without_api_key(mock_redis_service):
    """
    Create a test client without API key configured.

    Args:
        mock_redis_service: Mocked Redis service

    Returns:
        TestClient: A test client without API key
    """
    # Patch the redis_service with our mock
    import api.rate_limiting

    original_redis_service = api.rate_limiting.redis_service
    api.rate_limiting.redis_service = mock_redis_service

    client = TestClient(create_test_app(api_key=None))

    # Restore original service after test
    yield client

    api.rate_limiting.redis_service = original_redis_service
