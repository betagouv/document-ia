from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO
from document_ia_infra.data.webhook.entity.webhook import WebHookEntity
from document_ia_infra.service.webhook_encryption_service import (
    webhook_encryption_service,
)


def entity_to_dto(entity: WebHookEntity) -> WebHookDTO:
    return WebHookDTO(
        id=entity.id,
        organization_id=entity.organization_id,
        url=entity.url,
        headers=webhook_encryption_service.decrypt_headers(entity.encrypted_headers),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def dto_to_entity(dto: WebHookDTO) -> WebHookEntity:
    return WebHookEntity(
        id=dto.id,
        organization_id=dto.organization_id,
        url=dto.url,
        encrypted_headers=webhook_encryption_service.encrypt_headers(dto.headers),
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )
