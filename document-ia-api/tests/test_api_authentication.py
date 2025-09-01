"""
Integration tests for API key authentication.

This module tests the authentication flow for the Document IA API,
covering various scenarios including missing, invalid, and valid API keys.
"""

from fastapi import status


class TestAPIAuthentication:
    """Test cases for API key authentication."""

    def test_no_api_key_returns_403(self, client_with_api_key):
        """
        Test that requests without API key return 403 Forbidden.

        This tests the scenario where no X-API-KEY header is provided.
        """
        # Act: Make request without API key header
        response = client_with_api_key.get("/api/v1/")

        # Assert: Should return 403 Forbidden (FastAPI default for missing auth)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "detail" in response.json()
        assert response.json()["detail"] == "Not authenticated"

    def test_invalid_api_key_returns_401(self, client_with_api_key):
        """
        Test that requests with invalid API key return 401 Unauthorized.

        This tests the scenario where an API key is provided but it doesn't match
        the configured API key.
        """
        # Act: Make request with invalid API key
        response = client_with_api_key.get(
            "/api/v1/", headers={"X-API-KEY": "invalid_api_key"}
        )

        # Assert: Should return 401 Unauthorized
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "detail" in response.json()
        assert response.json()["detail"] == "No permission -- see authorization schemes"

    def test_valid_api_key_returns_200(self, client_with_api_key, valid_api_key):
        """
        Test that requests with valid API key return 200 OK with expected data.

        This tests the nominal case where a valid API key is provided.
        """
        # Act: Make request with valid API key
        response = client_with_api_key.get(
            "/api/v1/", headers={"X-API-KEY": valid_api_key}
        )

        # Assert: Should return 200 OK with expected response structure
        assert response.status_code == status.HTTP_200_OK

        response_data = response.json()
        assert "status" in response_data

        # Verify response content
        assert response_data["status"] == "success"

    def test_server_not_configured_with_api_key_returns_500(
        self, client_without_api_key
    ):
        """
        Test that requests fail when server is not configured with API key.

        This tests the scenario where the server doesn't have an API_KEY configured.
        """
        # Act: Make request with any API key when server is not configured
        response = client_without_api_key.get(
            "/api/v1/", headers={"X-API-KEY": "any-api-key"}
        )

        # Assert: Should return 500 Internal Server Error
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "detail" in response.json()
        assert response.json()["detail"] == "API_KEY not configured on server"

    def test_api_key_case_sensitive(self, client_with_api_key, valid_api_key):
        """
        Test that API key validation is case sensitive.

        This ensures that API keys are compared exactly, including case sensitivity.
        """
        # Create a case-variant of the valid API key
        case_variant = (
            valid_api_key.upper() if valid_api_key.islower() else valid_api_key.lower()
        )

        # Act: Make request with case-variant API key
        response = client_with_api_key.get(
            "/api/v1/", headers={"X-API-KEY": case_variant}
        )

        # Assert: Should return 401 Unauthorized due to case mismatch
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "No permission -- see authorization schemes"

    def test_empty_api_key_returns_403(self, client_with_api_key):
        """
        Test that empty API key returns 403 Forbidden.

        This tests the edge case where an empty string is provided as API key.
        """
        # Act: Make request with empty API key
        response = client_with_api_key.get("/api/v1/", headers={"X-API-KEY": ""})

        # Assert: Should return 403 Forbidden (FastAPI treats empty as missing)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "Not authenticated"

    def test_whitespace_only_api_key_returns_401(self, client_with_api_key):
        """
        Test that whitespace-only API key returns 401 Unauthorized.

        This tests the edge case where only whitespace characters are provided.
        """
        # Act: Make request with whitespace-only API key
        response = client_with_api_key.get("/api/v1/", headers={"X-API-KEY": "   "})

        # Assert: Should return 401 Unauthorized
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "No permission -- see authorization schemes"


class TestAPIAuthenticationHeaders:
    """Test cases for API key header variations."""

    def test_api_key_header_case_insensitive(self, client_with_api_key, valid_api_key):
        """
        Test that API key header name is case insensitive.

        FastAPI should accept the header regardless of case.
        """
        # Act: Make request with different header case variations
        headers_variations = [
            {"x-api-key": valid_api_key},
            {"X-API-KEY": valid_api_key},
            {"X-Api-Key": valid_api_key},
            {"x-API-Key": valid_api_key},
        ]

        for headers in headers_variations:
            response = client_with_api_key.get("/api/v1/", headers=headers)

            # Assert: All variations should work
            assert response.status_code == status.HTTP_200_OK, (
                f"Failed with headers: {headers}"
            )
            assert response.json()["status"] == "success"

    def test_multiple_api_key_headers_uses_last(
        self, client_with_api_key, valid_api_key
    ):
        """
        Test behavior when multiple API key headers are provided.

        This tests what happens when duplicate headers are sent.
        """
        # Act: Make request with multiple API key headers
        response = client_with_api_key.get(
            "/api/v1/",
            headers={
                "X-API-KEY": valid_api_key,
                "x-api-key": "invalid_api_key",  # Duplicate with different case
            },
        )

        # Assert: FastAPI seems to use the last header or reject the request
        # This test documents the actual behavior
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "No permission -- see authorization schemes"


class TestAPIAuthenticationErrorMessages:
    """Test cases for error message consistency."""

    def test_unauthorized_error_message_consistency(self, client_with_api_key):
        """
        Test that unauthorized error messages are consistent.

        This ensures all unauthorized requests return the same error format.
        """
        invalid_keys = ["wrong-key", "   ", "different-key"]

        for invalid_key in invalid_keys:
            response = client_with_api_key.get(
                "/api/v1/", headers={"X-API-KEY": invalid_key}
            )

            # Assert: All should return the same error format
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
            assert "detail" in response.json()
            assert (
                response.json()["detail"]
                == "No permission -- see authorization schemes"
            )
