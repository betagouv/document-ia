from dataclasses import dataclass


@dataclass
class S3ConnectivityStatus:
    connected: bool
    credentials_valid: bool
    bucket_exists: bool

    endpoint: str
    bucket_name: str
    errors: list[str]

    @property
    def is_healthy(self):
        return self.connected and self.credentials_valid and self.bucket_exists

    @classmethod
    def default(cls, endpoint: str, bucket_name: str) -> "S3ConnectivityStatus":
        return cls(
            connected=False,
            credentials_valid=False,
            bucket_exists=False,
            endpoint=endpoint,
            bucket_name=bucket_name,
            errors=[],
        )
