from document_ia_api.api.contracts.api_key.api_key import APIKeyResult
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO


def map_api_key_dto_to_api_result(dto: ApiKeyDTO) -> APIKeyResult:
    return APIKeyResult(
        id=str(dto.id),
        prefix=dto.prefix,
        status=dto.status,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
    )
