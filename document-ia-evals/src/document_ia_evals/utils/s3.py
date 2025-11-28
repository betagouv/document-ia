"""S3 utility functions for file upload and management."""

import json
import time
from typing import Any, Protocol

import boto3
from botocore.exceptions import ClientError

from document_ia_evals.utils.config import config


class S3ClientProtocol(Protocol):
    """Protocol for S3 client type."""
    
    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> Any:
        ...


def get_s3_client() -> Any:
    """Create and return an S3 client configured from environment."""
    return boto3.client(
        's3',
        endpoint_url=config.S3_ENDPOINT,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        region_name=config.S3_REGION
    )


def upload_file_to_s3(
    s3_client: S3ClientProtocol,
    bucket: str,
    key: str,
    file_content: bytes,
    content_type: str,
    retries: int = 3,
    delay: int = 1
) -> bool:
    """
    Upload a file to S3 with retry logic.
    
    Args:
        s3_client: S3 client instance
        bucket: S3 bucket name
        key: S3 object key
        file_content: File content as bytes
        content_type: MIME type of the file
        retries: Number of retry attempts
        delay: Initial delay between retries (doubles on each retry)
    
    Returns:
        True if upload succeeded
    
    Raises:
        Exception: If upload fails after all retries
    """
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_content,
            ContentType=content_type
        )
        return True
    except ClientError as e:
        if retries > 1:
            time.sleep(delay)
            return upload_file_to_s3(
                s3_client, bucket, key, file_content,
                content_type, retries - 1, delay * 2
            )
        else:
            raise Exception(f"Failed to upload {key} to S3: {e}")


def get_file_extension(content_type: str) -> str:
    """
    Determine file extension from content type.
    
    Args:
        content_type: MIME type of the file
    
    Returns:
        File extension including the dot (e.g., '.pdf', '.jpg')
    """
    if 'pdf' in content_type.lower():
        return '.pdf'
    elif 'jpeg' in content_type.lower():
        return '.jpg'
    else:
        return '.png'


def upload_to_s3_with_task(
    s3_client: S3ClientProtocol,
    bucket: str,
    prefix: str,
    file_id: str,
    file_content: bytes,
    content_type: str,
    task_data: dict[str, Any],
    retries: int = 3,
    delay: int = 1
) -> bool:
    """
    Upload raw file and task JSON to S3 in Label Studio format.
    
    Args:
        s3_client: S3 client instance
        bucket: S3 bucket name
        prefix: S3 prefix path for the dataset
        file_id: Unique identifier for the file (without extension)
        file_content: File content as bytes
        content_type: MIME type of the file
        task_data: Label Studio task data as dictionary
        retries: Number of retry attempts
        delay: Initial delay between retries
    
    Returns:
        True if both uploads succeeded
    
    Raises:
        Exception: If upload fails after all retries
    """
    try:
        # Determine file extension
        ext = get_file_extension(content_type)
        
        # Upload raw file to source subdirectory
        raw_key = f"{prefix}/source/{file_id}{ext}"
        upload_file_to_s3(
            s3_client=s3_client,
            bucket=bucket,
            key=raw_key,
            file_content=file_content,
            content_type=content_type,
            retries=retries,
            delay=delay
        )
        
        # Upload JSON task
        json_key = f"{prefix}/tasks/{file_id}.json"
        json_data = json.dumps(task_data, ensure_ascii=False, indent=2)
        upload_file_to_s3(
            s3_client=s3_client,
            bucket=bucket,
            key=json_key,
            file_content=json_data.encode('utf-8'),
            content_type='application/json',
            retries=retries,
            delay=delay
        )
        
        return True
    except ClientError as e:
        raise Exception(f"Failed to upload {file_id} to S3: {e}")


def build_s3_url(bucket: str, key: str) -> str:
    """
    Build an S3 URL from bucket and key.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
    
    Returns:
        S3 URL in the format s3://bucket/key
    """
    return f"s3://{bucket}/{key}"

