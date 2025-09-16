import logging
from typing import Tuple, Optional

import magic
from fastapi import UploadFile, HTTPException

from document_ia_api.core.config import settings
from document_ia_api.core.model.file_info import FileInfo

logger = logging.getLogger(__name__)


class FileValidator:
    """Service for validating uploaded files."""

    # Reverse mapping for validation - built from settings
    EXTENSION_TO_MIME: dict[str, str] = {}
    for mime_type, extensions in settings.ALLOWED_MIME_TYPES.items():
        for ext in extensions:
            EXTENSION_TO_MIME[ext.lower()] = mime_type

    @classmethod
    def validate_file(
        cls, file: UploadFile
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate uploaded file for size, type, and content.

        Args:
            file: FastAPI UploadFile object

        Returns:
            Tuple of (is_valid, error_message, detected_mime_type)
        """
        try:
            # Check file size
            if not cls._validate_file_size(file):
                return (
                    False,
                    f"File size exceeds maximum limit of {settings.MAX_FILE_SIZE / (1024 * 1024)}MB",
                    None,
                )

            # Check file extension
            if not cls._validate_file_extension(file):
                return (
                    False,
                    "File extension not supported. Supported formats: PDF, JPG, PNG",
                    None,
                )

            # Read file content for MIME type detection
            file_content = file.file.read()
            file.file.seek(0)  # Reset file pointer

            # Detect MIME type from content
            detected_mime = cls._detect_mime_type(file_content)
            if not detected_mime:
                return False, "Could not detect file type from content", None

            # Validate detected MIME type
            if not cls._validate_mime_type(detected_mime):
                return (
                    False,
                    f"File type '{detected_mime}' not supported. Supported types: {', '.join(settings.ALLOWED_MIME_TYPES)}",
                    None,
                )

            # Ensure filename is present if the _validate_mime_type pass the filename is not None
            assert file.filename

            # Cross-validate extension vs detected MIME type
            if not cls._cross_validate_extension_and_mime(file, detected_mime):
                return (
                    False,
                    f"File extension '{file.filename.split('.')[-1]}' does not match detected content type '{detected_mime}'",
                    None,
                )

            logger.info(
                f"File validation successful: {file.filename} ({detected_mime})"
            )
            return True, None, detected_mime

        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return False, f"File validation failed: {str(e)}", None

    @classmethod
    def _validate_file_size(cls, file: UploadFile) -> bool:
        """Validate file size against configured limit."""
        try:
            # Get file size by reading content
            current_pos = file.file.tell()
            file.file.seek(0, 2)  # Seek to end
            file_size = file.file.tell()
            file.file.seek(current_pos)  # Restore position

            return file_size <= settings.MAX_FILE_SIZE
        except Exception as e:
            logger.error(f"Error checking file size: {e}")
            return False

    @classmethod
    def _validate_file_extension(cls, file: UploadFile) -> bool:
        """Validate file extension."""
        if not file.filename or "." not in file.filename:
            return False

        extension = "." + file.filename.split(".")[-1].lower()
        return extension in cls.EXTENSION_TO_MIME

    @classmethod
    def _detect_mime_type(cls, file_content: bytes) -> Optional[str]:
        """Detect MIME type from file content using python-magic."""
        try:
            # Use python-magic to detect MIME type from content
            detected = magic.from_buffer(file_content, mime=True)
            return detected
        except Exception as e:
            logger.error(f"Error detecting MIME type: {e}")
            return None

    @classmethod
    def _validate_mime_type(cls, mime_type: str) -> bool:
        """Validate detected MIME type against allowed types."""
        return mime_type in settings.ALLOWED_MIME_TYPES

    @classmethod
    def _cross_validate_extension_and_mime(
        cls, file: UploadFile, detected_mime: str
    ) -> bool:
        """Cross-validate file extension with detected MIME type."""
        if not file.filename or "." not in file.filename:
            return False

        extension = "." + file.filename.split(".")[-1].lower()
        expected_mime = cls.EXTENSION_TO_MIME.get(extension)

        if not expected_mime:
            return False

        # Allow some flexibility in MIME type detection
        # Some JPEG files might be detected as 'image/jpeg' or 'image/jpg'
        if detected_mime == "image/jpg" and expected_mime == "image/jpeg":
            return True

        return detected_mime == expected_mime

    @classmethod
    def get_file_info(cls, file: UploadFile) -> Optional[FileInfo]:
        """Get comprehensive file information."""
        try:
            current_pos = file.file.tell()
            file.file.seek(0, 2)  # Seek to end
            file_size = file.file.tell()
            file.file.seek(current_pos)  # Restore position

            if file.filename is None:
                raise ValueError("Filename is None")

            extension = (
                "." + file.filename.split(".")[-1].lower()
                if "." in file.filename
                else ""
            )

            allowed_types = list(settings.ALLOWED_MIME_TYPES.keys())

            return FileInfo(
                filename=file.filename,
                size=file_size,
                extension=extension,
                content_type=file.content_type,
                max_size_allowed=settings.MAX_FILE_SIZE,
                allowed_types=allowed_types,
            )
        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return None


def validate_uploaded_file(file: UploadFile) -> str:
    """
    Validate uploaded file and return detected MIME type.

    Args:
        file: FastAPI UploadFile object

    Returns:
        Detected MIME type if valid

    Raises:
        HTTPException: If file validation fails
    """
    is_valid, error_message, detected_mime = FileValidator.validate_file(file)

    if not is_valid or detected_mime is None:
        file_info = FileValidator.get_file_info(file)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "file_validation_error",
                "message": error_message,
                "file_info": file_info.to_dict() if file_info else None,
            },
        )

    return detected_mime
