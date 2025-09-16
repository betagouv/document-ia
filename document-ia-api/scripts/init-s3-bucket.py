#!/usr/bin/env python3
"""
Simple script to initialize MinIO bucket on startup.
Uses boto3 to connect to MinIO and create the default bucket if it doesn't exist.
"""

import os
import sys
import boto3
from botocore.exceptions import ClientError
from pathlib import Path

import dotenv

# Load .env file from project root (two levels up from scripts/)
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
dotenv.load_dotenv(env_path)


def create_bucket_if_not_exists(client, bucket_name: str) -> bool:
    """Create bucket if it doesn't exist."""
    print(f"🔍 Checking if bucket '{bucket_name}' exists...")

    try:
        # Check if bucket exists
        client.head_bucket(Bucket=bucket_name)
        print(f"✅ Bucket '{bucket_name}' already exists")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404":
            # Bucket doesn't exist, create it
            print(f"📦 Creating bucket '{bucket_name}'...")
            try:
                client.create_bucket(Bucket=bucket_name)
                print(f"✅ Bucket '{bucket_name}' created successfully")
                return True
            except ClientError as create_error:
                print(f"❌ Failed to create bucket '{bucket_name}': {create_error}")
                return False
        else:
            print(f"❌ Error checking bucket '{bucket_name}': {e}")
            return False

    except Exception as e:
        print(f"❌ Unexpected error checking bucket '{bucket_name}': {e}")
        return False


def main():
    """Main function to initialize S3 bucket."""
    print("🚀 Starting S3 bucket initialization...")
    print(f"📁 Looking for .env file at: {env_path}")
    print(f"📁 .env file exists: {env_path.exists()}")

    # Get configuration from environment variables
    endpoint_url = os.getenv("S3_ENDPOINT_URL")
    bucket_name = os.getenv("S3_BUCKET_NAME")
    access_key = os.getenv("S3_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY")
    region = os.getenv("S3_REGION_NAME")
    use_ssl = os.getenv("S3_USE_SSL", "false").lower() == "true"

    # Check if required variables are set
    if not bucket_name:
        print("❌ S3_BUCKET_NAME is not set!")
        sys.exit(1)
    if not endpoint_url:
        print("❌ S3_ENDPOINT_URL is not set!")
        sys.exit(1)
    if not access_key:
        print("❌ S3_ACCESS_KEY_ID is not set!")
        sys.exit(1)
    if not secret_key:
        print("❌ S3_SECRET_ACCESS_KEY is not set!")
        sys.exit(1)

    # Create S3 client
    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=use_ssl,
        )
    except Exception as e:
        print(f"❌ Failed to create S3 client: {e}")
        sys.exit(1)

    # Create bucket if it doesn't exist
    if not create_bucket_if_not_exists(client, bucket_name):
        sys.exit(1)

    print("🎉 S3 bucket initialization completed successfully!")


if __name__ == "__main__":
    main()
