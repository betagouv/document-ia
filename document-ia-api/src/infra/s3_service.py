import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from infra.config import settings

logger = logging.getLogger(__name__)


class S3Service:
    """Service for handling S3/MinIO file operations."""

    def __init__(self):
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION_NAME,
            use_ssl=settings.S3_USE_SSL,
        )
        self.bucket_name = settings.S3_BUCKET_NAME

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
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
            file_extension = filename.split(".")[-1] if "." in filename else ""
            s3_key = f"uploads/{datetime.now().strftime('%Y/%m/%d')}/{file_id}.{file_extension}"

            # Prepare S3 metadata
            s3_metadata = {
                "original-filename": filename,
                "content-type": content_type,
                "upload-timestamp": datetime.now().isoformat(),
                "file-id": file_id,
            }

            # Add custom metadata if provided
            if metadata:
                for key, value in metadata.items():
                    s3_metadata[f"custom-{key}"] = str(value)

            # Upload file to S3
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=file_data,
                    ContentType=content_type,
                    Metadata=s3_metadata,
                ),
            )

            # Generate presigned URL for access (optional)
            presigned_url = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": s3_key},
                    ExpiresIn=3600,  # 1 hour
                ),
            )

            result = {
                "file_id": file_id,
                "s3_key": s3_key,
                "filename": filename,
                "content_type": content_type,
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
        """
        Delete a file from S3/MinIO.

        Args:
            s3_key: S3 key of the file to delete

        Returns:
            True if deletion was successful
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.delete_object(
                    Bucket=self.bucket_name, Key=s3_key
                ),
            )

            logger.info(f"File deleted successfully: {s3_key}")
            return True

        except ClientError as e:
            logger.error(f"Failed to delete file {s3_key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during file deletion: {e}")
            return False

    async def get_file_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a file in S3/MinIO.

        Args:
            s3_key: S3 key of the file

        Returns:
            Dict containing file information or None if not found
        """
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key),
            )

            return {
                "s3_key": s3_key,
                "size": response["ContentLength"],
                "content_type": response["ContentType"],
                "last_modified": response["LastModified"].isoformat(),
                "metadata": response.get("Metadata", {}),
            }

        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            logger.error(f"Failed to get file info for {s3_key}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting file info: {e}")
            return None

    async def check_bucket_exists(self) -> bool:
        """
        Check if the configured S3 bucket exists.

        Returns:
            True if bucket exists, False otherwise
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.s3_client.head_bucket(Bucket=self.bucket_name)
            )
            return True
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                logger.warning(f"S3 bucket '{self.bucket_name}' does not exist")
                return False
            logger.error(f"S3 bucket check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking bucket: {e}")
            return False

    async def check_connectivity(self) -> Dict[str, Any]:
        """
        Comprehensive S3 connectivity check.

        Performs multiple checks:
        1. Basic connection test (ping)
        2. Credentials validation
        3. Bucket existence check

        Returns:
            Dict containing connectivity status and details
        """
        connectivity_status = {
            "connected": False,
            "credentials_valid": False,
            "bucket_exists": False,
            "is_healthy": False,
            "endpoint": settings.S3_ENDPOINT_URL,
            "bucket_name": self.bucket_name,
            "errors": [],
        }

        try:
            # Test 1: Basic connection and credentials
            logger.info("Testing S3 connectivity...")
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.s3_client.list_buckets()
            )
            connectivity_status["connected"] = True
            connectivity_status["credentials_valid"] = True
            logger.info("S3 connection and credentials validated successfully")

        except NoCredentialsError as e:
            error_msg = f"S3 credentials not configured properly: {e}"
            connectivity_status["errors"].append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["InvalidAccessKeyId", "SignatureDoesNotMatch"]:
                error_msg = f"S3 credentials invalid: {e}"
                connectivity_status["errors"].append(error_msg)
                logger.error(error_msg)
                return connectivity_status
            else:
                error_msg = f"S3 connection failed: {e}"
                connectivity_status["errors"].append(error_msg)
                logger.error(error_msg)
                return connectivity_status

        except Exception as e:
            error_msg = f"Unexpected error during S3 connectivity check: {e}"
            connectivity_status["errors"].append(error_msg)
            logger.error(error_msg)
            return connectivity_status

        # Test 2: Check if bucket exists
        try:
            bucket_exists = await self.check_bucket_exists()
            connectivity_status["bucket_exists"] = bucket_exists

            if bucket_exists:
                logger.info(f"S3 bucket '{self.bucket_name}' is accessible")
            else:
                logger.warning(f"S3 bucket '{self.bucket_name}' does not exist")

        except Exception as e:
            error_msg = f"Error during bucket check: {e}"
            connectivity_status["errors"].append(error_msg)
            logger.error(error_msg)

        # Determine overall health status
        connectivity_status["is_healthy"] = (
            connectivity_status["connected"]
            and connectivity_status["credentials_valid"]
            and connectivity_status["bucket_exists"]
        )

        return connectivity_status


# Global S3 service instance
s3_service = S3Service()
