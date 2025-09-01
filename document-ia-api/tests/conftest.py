"""
Pytest configuration and fixtures for Document IA API tests.

This module provides common fixtures and configuration for all integration tests.
"""

import os
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add the src directory to Python path for imports
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.routes import router


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
        SERVER_HOST = "0.0.0.0"
        SERVER_PORT = 8000
        API_KEY = api_key

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

    # Override the settings in the auth module
    import api.auth

    api.auth.settings = TestSettings()

    # Include API routes
    app.include_router(router, prefix="/api", tags=["API"])

    return app


@pytest.fixture
def client():
    """
    Create a test client for the FastAPI application.

    Returns:
        TestClient: A test client instance for making HTTP requests
    """
    return TestClient(create_test_app())


@pytest.fixture
def valid_api_key():
    """
    Provide a valid API key for testing.

    Returns:
        str: A valid API key for authentication
    """
    return "test-api-key-12345"


@pytest.fixture
def client_with_api_key(valid_api_key):
    """
    Create a test client with a valid API key configured.

    Args:
        valid_api_key: The valid API key to use in settings

    Returns:
        TestClient: A test client with API key configured
    """
    return TestClient(create_test_app(api_key=valid_api_key))


@pytest.fixture
def client_without_api_key():
    """
    Create a test client without API key configured.

    Returns:
        TestClient: A test client without API key
    """
    return TestClient(create_test_app(api_key=None))
