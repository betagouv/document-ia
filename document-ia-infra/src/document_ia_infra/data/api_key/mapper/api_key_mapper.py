from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.entity.api_key import ApiKeyEntity
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.mapper_helper import get_relationship_entity_if_loaded


def entity_to_dto(entity: ApiKeyEntity) -> ApiKeyDTO:
    try:
        status = ApiKeyStatus(entity.status)
    except Exception:
        status = ApiKeyStatus.ACTIVE

    ## Avoid circular import by lazy-loading the organization mapper
    from document_ia_infra.data.organization.mapper.organization_mapper import (
        entity_to_dto as organization_entity_to_dto,
    )

    return ApiKeyDTO(
        id=entity.id,
        organization_id=entity.organization_id,
        organization=get_relationship_entity_if_loaded(
            entity, "organization", organization_entity_to_dto
        ),
        key_hash=entity.key_hash,
        prefix=entity.prefix,
        status=status,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def dto_to_entity(dto: ApiKeyDTO) -> ApiKeyEntity:
    return ApiKeyEntity(
        id=dto.id,
        organization_id=dto.organization_id,
        key_hash=dto.key_hash,
        prefix=dto.prefix,
        status=dto.status.value,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )
