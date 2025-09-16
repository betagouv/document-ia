from unittest.mock import MagicMock

from core.file_validator import FileValidator


class TestFileValidation:
    """Test cases for file validation logic."""

    def test_validate_pdf_file(self):
        """Test PDF file validation."""

        # Create a proper mock file object
        mock_file = MagicMock()
        mock_file.filename = "test.pdf"
        mock_file.content_type = "application/pdf"

        # Mock the file-like object properly
        mock_file_obj = MagicMock()
        mock_file_obj.read.return_value = (
            b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
        )
        mock_file_obj.tell.side_effect = [
            0,
            1024,
        ]  # First call returns 0, second returns file size
        mock_file_obj.seek = MagicMock()
        mock_file.file = mock_file_obj

        is_valid, error, mime_type = FileValidator.validate_file(mock_file)
        assert is_valid
        assert error is None
        assert mime_type == "application/pdf"

    def test_validate_png_file(self):
        """Test PNG file validation."""

        # Create a proper mock file object
        mock_file = MagicMock()
        mock_file.filename = "test.png"
        mock_file.content_type = "image/png"

        # Mock the file-like object properly
        mock_file_obj = MagicMock()
        mock_file_obj.read.return_value = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178\xea\x00\x00\x00\x00IEND\xaeB`\x82"
        mock_file_obj.tell.side_effect = [
            0,
            1024,
        ]  # First call returns 0, second returns file size
        mock_file_obj.seek = MagicMock()
        mock_file.file = mock_file_obj

        is_valid, error, mime_type = FileValidator.validate_file(mock_file)
        assert is_valid
        assert error is None
        assert mime_type == "image/png"

    def test_validate_unsupported_file_type(self):
        """Test unsupported file type validation."""

        # Create a proper mock file object
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.content_type = "text/plain"

        # Mock the file-like object properly
        mock_file_obj = MagicMock()
        mock_file_obj.read.return_value = b"This is a text file"
        mock_file_obj.tell.side_effect = [
            0,
            1024,
        ]  # First call returns 0, second returns file size
        mock_file_obj.seek = MagicMock()
        mock_file.file = mock_file_obj

        is_valid, error, mime_type = FileValidator.validate_file(mock_file)
        assert not is_valid
        assert error is not None
        assert "not supported" in error
