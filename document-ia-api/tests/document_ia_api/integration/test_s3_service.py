from unittest.mock import patch, MagicMock

import pytest

from document_ia_api.infra.s3_service import S3Service


class TestS3Service:
    """Test cases for S3 service."""

    def test_s3_service_initialization(self):
        """Test S3 service initialization."""

        service = S3Service()
        assert service.bucket_name is not None
        assert service.s3_client is not None

    @pytest.mark.asyncio
    async def test_s3_upload_file(self):
        """Test S3 file upload."""

        # Mock boto3 client at the module level
        with patch("document_ia_api.infra.s3_service.boto3.client") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.return_value = mock_client

            # Mock upload response
            mock_client.put_object.return_value = None
            mock_client.generate_presigned_url.return_value = (
                "http://example.com/presigned"
            )

            # Create service instance after mocking
            service = S3Service()

            result = await service.upload_file(
                file_data=b"test content",
                filename="test.pdf",
                content_type="application/pdf",
                metadata={"test": "value"},
            )

            assert result["file_id"] is not None
            assert result["presigned_url"] == "http://example.com/presigned"

    @pytest.mark.asyncio
    async def test_s3_connectivity_check_success(self):
        """Test S3 connectivity check with successful connection."""

        with patch("document_ia_api.infra.s3_service.boto3.client") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.return_value = mock_client

            # Mock successful list_buckets call
            mock_client.list_buckets.return_value = {"Buckets": []}

            # Mock successful head_bucket call (bucket exists)
            mock_client.head_bucket.return_value = {}

            service = S3Service()
            result = await service.check_connectivity()

            assert result.connected is True
            assert result.credentials_valid is True
            assert result.bucket_exists is True
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_s3_connectivity_check_credentials_error(self):
        """Test S3 connectivity check with invalid credentials."""

        with patch("document_ia_api.infra.s3_service.boto3.client") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.return_value = mock_client

            # Mock NoCredentialsError
            from botocore.exceptions import NoCredentialsError

            mock_client.list_buckets.side_effect = NoCredentialsError()

            service = S3Service()
            result = await service.check_connectivity()

            assert result.connected is False
            assert result.credentials_valid is False
            assert len(result.errors) > 0
            assert "credentials not configured" in result.errors[0]

    @pytest.mark.asyncio
    async def test_s3_connectivity_check_bucket_not_exists(self):
        """Test S3 connectivity check when bucket doesn't exist."""

        with patch("document_ia_api.infra.s3_service.boto3.client") as mock_boto3:
            mock_client = MagicMock()
            mock_boto3.return_value = mock_client

            # Mock successful list_buckets call
            mock_client.list_buckets.return_value = {"Buckets": []}

            # Mock bucket not found (404 error)
            from botocore.exceptions import ClientError

            error_response = {"Error": {"Code": "404"}}
            mock_client.head_bucket.side_effect = ClientError(
                error_response, "HeadBucket"
            )

            service = S3Service()
            result = await service.check_connectivity()

            assert result.connected is True
            assert result.credentials_valid is True
            assert result.bucket_exists is False
