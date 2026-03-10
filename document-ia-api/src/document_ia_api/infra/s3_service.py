import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from botocore.exceptions import ClientError, NoCredentialsError

from document_ia_api.infra.s3.s3_connectivity_status import S3ConnectivityStatus
from document_ia_infra.s3.s3_manager import S3Manager
from document_ia_infra.s3.s3_settings import s3_settings

logger = logging.getLogger(__name__)


class S3Service:
    """Service for handling S3/MinIO file operations."""

    def __init__(self):
        self.s3_manager = S3Manager()

    async def upload_file(
        self,
        file_data: bytes,
        filename: Optional[str],
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Upload a file to S3/MinIO.

        Args:
            file_data: File content as bytes
            filename: Original filename
            content_type: MIME type of the file
            metadata: Optional metadata to store with the file

        Returns:
            Dict containing upload information
        """
        try:
            # Generate unique key for the file
            file_id = str(uuid.uuid4())

            if filename is None:
                final_filename = f"{file_id}.{content_type}"
            else:
                final_filename = filename

            file_extension = (
                final_filename.split(".")[-1] if "." in final_filename else ""
            )
            s3_key = f"uploads/{datetime.now().strftime('%Y/%m/%d')}/{file_id}.{file_extension}"

            # Prepare S3 metadata
            s3_metadata = {
                "original-filename": final_filename,
                "content-type": content_type,
                "upload-timestamp": datetime.now().isoformat(),
                "file-id": file_id,
            }

            # Add custom metadata if provided
            if metadata:
                for key, value in metadata.items():
                    s3_metadata[f"custom-{key}"] = str(value)

            # Upload file to S3
            self.s3_manager.upload_file(s3_key, file_data, content_type, s3_metadata)
            presigned_url = self.s3_manager.get_presigned_url(s3_key)

            result = {
                "file_id": file_id,
                "s3_key": s3_key,
                "filename": filename,
                "content_type": content_type,
                "file_extension": file_extension,
                "size": len(file_data),
                "upload_timestamp": datetime.now().isoformat(),
                "presigned_url": presigned_url,
            }

            logger.info(f"File uploaded successfully: {file_id} ({filename})")
            return result

        except NoCredentialsError as e:
            logger.error(f"S3 credentials error: {e}")
            raise Exception("S3 credentials not configured properly")
        except ClientError as e:
            logger.error(f"S3 client error: {e}")
            raise Exception(f"Failed to upload file to S3: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during file upload: {e}")
            raise Exception(f"File upload failed: {e}")

    async def delete_file(self, s3_key: str) -> bool:
        return self.s3_manager.delete_file(s3_key)

    async def get_file_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        return self.s3_manager.get_file_info(s3_key)

    async def check_connectivity(self) -> S3ConnectivityStatus:
        """
        Comprehensive S3 connectivity check.

        Performs multiple checks:
        1. Basic connection test (ping)
        2. Credentials validation
        3. Bucket existence check

        Returns:
            S3ConnectivityStatus object with connectivity status and details
        """
        connectivity_status = S3ConnectivityStatus.default(
            endpoint=s3_settings.S3_ENDPOINT_URL,
            bucket_name=self.s3_manager.bucket_name,
        )

        try:
            # Test 1: Basic connection and credentials
            logger.info("Testing S3 connectivity...")
            self.s3_manager.check_connectivity()
            connectivity_status.connected = True
            connectivity_status.credentials_valid = True
            logger.info("S3 connection and credentials validated successfully")

        except NoCredentialsError as e:
            error_msg = f"S3 credentials not configured properly: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", {})
            if error_code in ["InvalidAccessKeyId", "SignatureDoesNotMatch"]:
                error_msg = f"S3 credentials invalid: {e}"
                connectivity_status.errors.append(error_msg)
                logger.error(error_msg)
                return connectivity_status
            else:
                error_msg = f"S3 connection failed: {e}"
                connectivity_status.errors.append(error_msg)
                logger.error(error_msg)
                return connectivity_status

        except Exception as e:
            error_msg = f"Unexpected error during S3 connectivity check: {e}"
            connectivity_status.errors.append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        # Test 2: Check if bucket exists
        bucket_exists = self.s3_manager.check_bucket_exists()
        connectivity_status.bucket_exists = bucket_exists

        if bucket_exists:
            logger.info(f"S3 bucket '{self.s3_manager.bucket_name}' is accessible")
        else:
            logger.warning(f"S3 bucket '{self.s3_manager.bucket_name}' does not exist")

        return connectivity_status


# Global S3 service instance
s3_service = S3Service()
