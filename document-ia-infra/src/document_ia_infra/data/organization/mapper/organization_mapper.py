from __future__ import annotations

from typing import Iterable, List

from document_ia_infra.data.mapper_helper import (
    get_relationships_entities_if_loaded_list,
)
from document_ia_infra.data.organization.dto.organization_dto import OrganizationDTO
from document_ia_infra.data.organization.entity.organization import OrganizationEntity
from document_ia_infra.data.organization.enum.platform_role import PlatformRole


def entity_to_dto(entity: OrganizationEntity) -> OrganizationDTO:
    """Map OrganizationEntity to OrganizationDTO.

    - Converts platform_role string to PlatformRole enum (defaults to STANDARD if unknown).
    - Does not trigger lazy-load for `api_keys`; only maps if already loaded.
    """
    try:
        role = PlatformRole(entity.platform_role)
    except Exception:
        role = PlatformRole.STANDARD

    ## Avoid circular import by lazy-loading the organization mapper
    from document_ia_infra.data.api_key.mapper.api_key_mapper import (
        entity_to_dto as api_key_entity_to_dto,
    )

    return OrganizationDTO(
        id=entity.id,
        contact_email=entity.contact_email,
        name=entity.name,
        platform_role=role,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        api_keys=get_relationships_entities_if_loaded_list(
            entity, "api_keys", api_key_entity_to_dto
        ),
    )


def entities_to_dtos(entities: Iterable[OrganizationEntity]) -> List[OrganizationDTO]:
    return [entity_to_dto(e) for e in entities]


def dto_to_entity(dto: OrganizationDTO) -> OrganizationEntity:
    """Map OrganizationDTO to OrganizationEntity instance (detached).

    - Converts PlatformRole enum to its string value for persistence.
    - Timestamps are copied as-is.
    """
    return OrganizationEntity(
        id=dto.id,
        contact_email=dto.contact_email,
        name=dto.name,
        platform_role=dto.platform_role.value,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )
