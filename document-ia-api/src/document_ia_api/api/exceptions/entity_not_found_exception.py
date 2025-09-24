from fastapi import HTTPException


class HttpEntityNotFoundException(HTTPException):
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            status_code=404,
            detail={
                "error": "entity_not_found",
                "message": f"{entity_name} with ID '{entity_id}' not found",
            },
        )
