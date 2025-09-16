import pytest
import json
import io

from unittest.mock import patch


class TestWorkflowExecution:
    """Test cases for workflow execution endpoint."""

    @pytest.fixture
    def valid_metadata(self):
        """Valid metadata for testing."""
        return {
            "$metadata": {
                "source": "email",
                "priority": "high",
                "tags": ["invoice", "urgent"],
                "user_id": "user123",
            }
        }

    @pytest.fixture
    def mock_pdf_file(self):
        """Mock PDF file for testing."""
        # Create a mock PDF file content
        pdf_content = (
            b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        )
        return io.BytesIO(pdf_content)

    @pytest.fixture
    def mock_image_file(self):
        """Mock image file for testing."""
        # Create a mock PNG file content
        png_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178\xea\x00\x00\x00\x00IEND\xaeB`\x82"
        return io.BytesIO(png_content)

    def test_execute_workflow_success_pdf(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_pdf_file
    ):
        """Test successful workflow execution with PDF file."""

        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["execution_id"] is not None
        assert data["data"]["workflow_id"] == "document-analysis-v1"
        assert data["data"]["status"] == "processing"
        assert "file_info" in data["data"]

    def test_execute_workflow_success_image(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_image_file
    ):
        """Test successful workflow execution with image file."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.png", mock_image_file, "image/png")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["file_info"]["filename"] == "test.png"

    def test_execute_workflow_missing_api_key(
        self, client_with_api_key, valid_metadata, mock_pdf_file
    ):
        """Test workflow execution without API key."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
        )

        assert response.status_code == 403

    def test_execute_workflow_invalid_api_key(
        self, client_with_api_key, valid_metadata, mock_pdf_file
    ):
        """Test workflow execution with invalid API key."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": "invalid-api-key"},
        )

        assert response.status_code == 401

    def test_execute_workflow_missing_file(
        self, client_with_api_key, valid_api_key, valid_metadata
    ):
        """Test workflow execution without file."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 422  # Validation error

    def test_execute_workflow_missing_metadata(
        self, client_with_api_key, valid_api_key, mock_pdf_file
    ):
        """Test workflow execution without metadata."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 422  # Validation error

    def test_execute_workflow_invalid_metadata_json(
        self, client_with_api_key, valid_api_key, mock_pdf_file
    ):
        """Test workflow execution with invalid JSON metadata."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": "invalid-json"},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "invalid_metadata"

    def test_execute_workflow_empty_metadata(
        self, client_with_api_key, valid_api_key, mock_pdf_file
    ):
        """Test workflow execution with empty metadata."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": "{}"},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "invalid_metadata"

    def test_execute_workflow_invalid_workflow_id(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_pdf_file
    ):
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v99/execute",  # Use a valid route pattern
            files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "workflow_not_found"

    def test_execute_workflow_s3_upload_failure(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_pdf_file
    ):
        """Test workflow execution when S3 upload fails."""
        with patch(
            "document_ia_api.application.services.workflow_service.s3_service.upload_file"
        ) as mock_upload:
            mock_upload.side_effect = Exception("S3 upload failed")

            response = client_with_api_key.post(
                "/api/v1/workflows/document-analysis-v1/execute",
                files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
                data={"metadata": json.dumps(valid_metadata)},
                headers={"X-API-KEY": valid_api_key},
            )

            assert response.status_code == 500
            data = response.json()
            assert data["detail"]["error"] == "s3_upload_error"

    def test_execute_workflow_unsupported_file_type(
        self, client_with_api_key, valid_api_key, valid_metadata
    ):
        """Test workflow execution with unsupported file type."""
        # Create a mock text file
        text_content = b"This is a text file"
        text_file = io.BytesIO(text_content)

        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("test.txt", text_file, "text/plain")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "file_validation_error"

    def test_execute_workflow_file_too_large(
        self, client_with_api_key, valid_api_key, valid_metadata
    ):
        """Test workflow execution with file too large."""
        # Create a mock large file (simulate > 25MB)
        large_content = b"x" * (26 * 1024 * 1024)  # 26MB
        large_file = io.BytesIO(large_content)

        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("large.pdf", large_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "file_validation_error"
        assert "exceeds maximum limit" in data["detail"]["message"]

    def test_execute_workflow_malicious_filename(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_pdf_file
    ):
        """Test workflow execution with potentially malicious filename."""
        response = client_with_api_key.post(
            "/api/v1/workflows/document-analysis-v1/execute",
            files={"file": ("../../../etc/passwd", mock_pdf_file, "application/pdf")},
            data={"metadata": json.dumps(valid_metadata)},
            headers={"X-API-KEY": valid_api_key},
        )

        # Should fail because the filename extension is not supported
        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "file_validation_error"

    def test_execute_workflow_rate_limit_exceeded(
        self, client_with_api_key, valid_api_key, valid_metadata, mock_pdf_file
    ):
        """Test workflow execution when rate limit is exceeded."""
        # Mock the redis service to return rate limit exceeded
        with patch("document_ia_api.api.rate_limiting.redis_service") as mock_redis:
            from document_ia_api.schemas.rate_limiting import RateLimitInfo
            from unittest.mock import AsyncMock

            # Mock rate limit exceeded
            mock_redis.check_rate_limit = AsyncMock(
                return_value=(
                    False,  # is_allowed = False
                    RateLimitInfo(
                        limit_exceeded=True,
                        remaining_minute=0,
                        remaining_daily=0,
                        reset_minute="2024-01-01T12:01:00",
                        reset_daily="2024-01-02T00:00:00",
                    ),
                )
            )

            response = client_with_api_key.post(
                "/api/v1/workflows/document-analysis-v1/execute",
                files={"file": ("test.pdf", mock_pdf_file, "application/pdf")},
                data={"metadata": json.dumps(valid_metadata)},
                headers={"X-API-KEY": valid_api_key},
            )

            # Should return 429 for rate limit exceeded
            assert response.status_code == 429
