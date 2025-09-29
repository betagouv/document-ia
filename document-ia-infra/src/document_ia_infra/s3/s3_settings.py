from pydantic import Field, SecretStr

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class S3Settings(BaseDocumentIaSettings):
    # S3/MinIO configuration
    S3_ENDPOINT_URL: str = Field(default="http://localhost:9000")
    S3_ACCESS_KEY_ID: SecretStr = Field(default_factory=lambda: SecretStr("minioadmin"))
    S3_SECRET_ACCESS_KEY: SecretStr = Field(
        default_factory=lambda: SecretStr("minioadmin")
    )
    S3_BUCKET_NAME: str = Field(default="document-ia")
    S3_REGION_NAME: str = Field(default="us-east-1")
    S3_USE_SSL: bool = Field(default=False)


s3_settings = S3Settings()
