from dataclasses import dataclass


@dataclass
class RedisConnectivityStatus:
    connected: bool
    is_healthy: bool
    host: str
    port: int
    db: int
    errors: list[str]
    nb_execution_to_process: int | None = None
    nb_execution_undelivered: int | None = None
    nb_execution_being_processed: int | None = None

    @classmethod
    def default(cls, host: str, port: int, db: int) -> "RedisConnectivityStatus":
        return cls(
            connected=False,
            is_healthy=False,
            host=host,
            port=port,
            db=db,
            errors=[],
            nb_execution_to_process=None,
            nb_execution_undelivered=None,
            nb_execution_being_processed=None,
        )
