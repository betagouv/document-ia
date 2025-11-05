from enum import Enum


class ApiKeyStatus(str, Enum):
    ACTIVE = "Active"
    REVOKED = "Revoked"
    EXPIRED = "Expired"
