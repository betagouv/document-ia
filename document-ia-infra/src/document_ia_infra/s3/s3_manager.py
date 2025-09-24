import logging
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3.client import S3Client
from mypy_boto3_s3.type_defs import ListBucketsOutputTypeDef, BucketTypeDef

from document_ia_infra.exception.s3_authentification_exception import (
    S3AuthentificationException,
)
from document_ia_infra.s3.s3_metadata_util import sanitize_metadata
from document_ia_infra.s3.s3_settings import s3_settings

logger = logging.getLogger(__name__)


class S3Manager:
    def __init__(self):
        self.s3_client: S3Client = boto3.client(  # pyright: ignore [reportUnknownMemberType]
            "s3",
            endpoint_url=s3_settings.S3_ENDPOINT_URL,
            aws_access_key_id=s3_settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=s3_settings.S3_SECRET_ACCESS_KEY,
            region_name=s3_settings.S3_REGION_NAME,
            use_ssl=s3_settings.S3_USE_SSL,
        )
        self.bucket_name = s3_settings.S3_BUCKET_NAME

    # The Exception need to be handled by the caller
    def upload_file(
        self,
        file_key: str,
        file_data: bytes,
        content_type: str,
        metadata: Optional[dict[str, str]] = None,
    ):
        if metadata is None:
            metadata = {}
        return self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=file_key,
            Body=file_data,
            ContentType=content_type,
            Metadata=sanitize_metadata(metadata),
        )

    # The Exception need to be handled by the caller
    def get_presigned_url(
        self,
        file_key: str,
        expiration: int = 3600,  # 1 hour
    ) -> str:
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": file_key},
            ExpiresIn=expiration,
        )

    def delete_file(self, s3_key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"File deleted successfully: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file {s3_key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during file deletion: {e}")
            return False

    def download_file(self, s3_key: str, output_path: str):
        try:
            self.s3_client.download_file(
                Bucket=self.bucket_name, Key=s3_key, Filename=output_path
            )
            logger.info(f"File downloaded successfully: {s3_key} to {output_path}")
        except ClientError as e:
            logger.error(f"Failed to download file {s3_key}: {e}")
            raise S3AuthentificationException()
        except Exception as e:
            logger.error(f"Unexpected error during file download: {e}")
            raise e

    def get_file_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)

            return {
                "s3_key": s3_key,
                "size": response["ContentLength"],
                "content_type": response["ContentType"],
                "last_modified": response["LastModified"].isoformat(),
                "metadata": response.get("Metadata", {}),
            }

        except ClientError as e:
            if e.response.get("Error", {}).get("Code", {}) == "404":
                return None
            logger.error(f"Failed to get file info for {s3_key}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting file info: {e}")
            return None

    def check_bucket_exists(self) -> bool:
        """
        Check if the configured S3 bucket exists.

        Returns:
            True if bucket exists, False otherwise
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", {})
            if error_code == "404":
                logger.warning(f"S3 bucket '{self.bucket_name}' does not exist")
                return False
            logger.error(f"S3 bucket check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking bucket: {e}")
            return False

    # The Exception need to be handled by the caller
    def check_connectivity(self):
        self.s3_client.list_buckets()

    def list_buckets(self) -> list[str]:
        try:
            response: ListBucketsOutputTypeDef = self.s3_client.list_buckets()
            buckets: list[BucketTypeDef] = response.get("Buckets", [])
            list_bucket_names: list[str] = []
            for bucket in buckets:
                if "Name" in bucket:
                    list_bucket_names.append(bucket["Name"])
            return list_bucket_names
        except ClientError as e:
            if e.response.get("Error", {}).get("Code", {}) == "404":
                return list()
            logger.error(f"Failed to list buckets: {e}")
            return list()
        except Exception as e:
            logger.error(f"Unexpected error getting file info: {e}")
            return list()
