import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from document_ia_infra.s3.s3_manager import S3Manager


@pytest.fixture
def mock_s3_manager():
    with patch("document_ia_infra.s3.s3_manager.boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        manager = S3Manager()
        yield manager, mock_client


def test_delete_file_success(mock_s3_manager, caplog):
    manager, mock_client = mock_s3_manager
    s3_key = "sensitive/customer_123/identity_document.pdf"

    with caplog.at_level(logging.INFO):
        result = manager.delete_file(s3_key)

    assert result is True
    mock_client.delete_object.assert_called_once_with(
        Bucket=manager.bucket_name, Key=s3_key
    )
    # Verification: raw s3_key must NOT appear in log messages (security requirement)
    assert s3_key not in caplog.text
    assert "File deleted successfully from S3" in caplog.text


def test_delete_file_client_error(mock_s3_manager, caplog):
    manager, mock_client = mock_s3_manager
    s3_key = "sensitive/customer_123/identity_document.pdf"

    mock_client.delete_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
        "DeleteObject",
    )

    with caplog.at_level(logging.INFO):
        result = manager.delete_file(s3_key)

    assert result is False
    assert s3_key not in caplog.text
    assert "Failed to delete file from S3" in caplog.text


def test_delete_file_unexpected_exception(mock_s3_manager, caplog):
    manager, mock_client = mock_s3_manager
    s3_key = "sensitive/customer_123/identity_document.pdf"

    mock_client.delete_object.side_effect = RuntimeError("Network timeout")

    with caplog.at_level(logging.INFO):
        result = manager.delete_file(s3_key)

    assert result is False
    assert s3_key not in caplog.text
    assert "Unexpected error during file deletion from S3" in caplog.text
