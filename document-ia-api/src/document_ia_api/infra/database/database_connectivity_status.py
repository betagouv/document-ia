from dataclasses import dataclass


@dataclass
class DatabaseConnectivityStatus:
    connected: bool
    is_healthy: bool
    errors: list[str]

    @classmethod
    def default(cls) -> "DatabaseConnectivityStatus":
        return cls(connected=False, is_healthy=False, errors=[])
