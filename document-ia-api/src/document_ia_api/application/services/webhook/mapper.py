from document_ia_api.api.contracts.webhook.webhook import WebHookResult
from document_ia_infra.data.webhook.dto.webhook_dto import WebHookDTO


def map_webhook_dto_to_api_result(dto: WebHookDTO) -> WebHookResult:
    return WebHookResult(
        id=str(dto.id),
        organization_id=dto.organization_id,
        url=dto.url,
        headers=dto.headers,
        created_at=dto.created_at.isoformat(),
        updated_at=dto.updated_at.isoformat(),
    )
