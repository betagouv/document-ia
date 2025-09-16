from dataclasses import dataclass


@dataclass
class RedisConnectivityStatus:
    connected: bool
    is_healthy: bool
    host: str
    port: int
    db: int
    errors: list[str]

    @classmethod
    def default(cls, host: str, port: int, db: int) -> "RedisConnectivityStatus":
        return cls(
            connected=False, is_healthy=False, host=host, port=port, db=db, errors=[]
        )
