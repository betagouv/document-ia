from fastapi import HTTPException

from document_ia_infra.redis.redis_settings import redis_settings


def capacity_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "execution_capacity_unavailable",
            "message": "Execution capacity is unavailable. Retry the request later.",
        },
        headers={"Retry-After": str(redis_settings.PUBLISH_RETRY_AFTER_SECONDS)},
    )
