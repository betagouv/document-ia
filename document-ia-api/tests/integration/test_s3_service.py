import pytest
from unittest.mock import patch, MagicMock

from src.infra.s3_service import S3Service


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
        with patch("infra.s3_service.boto3.client") as mock_boto3:
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
            assert result["s3_key"] is not None
            assert result["presigned_url"] == "http://example.com/presigned"
