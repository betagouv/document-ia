from datetime import datetime, timezone
from uuid import uuid4

from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.entity.api_key import ApiKeyEntity
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus
from document_ia_infra.data.api_key.mapper.api_key_mapper import (
    entity_to_dto,
    dto_to_entity,
)


def test_api_key_entity_to_dto_and_back():
    org_id = uuid4()
    now = datetime.now(timezone.utc)

    entity = ApiKeyEntity(
        id=uuid4(),
        organization_id=org_id,
        key_hash="hash-abc",
        prefix="ak_prefix",
        status=ApiKeyStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
    )

    dto = entity_to_dto(entity)
    assert dto.organization_id == org_id
    assert dto.key_hash == "hash-abc"
    assert dto.prefix == "ak_prefix"
    assert dto.status == ApiKeyStatus.ACTIVE
    assert dto.created_at == now

    roundtrip = dto_to_entity(dto)
    assert roundtrip.organization_id == org_id
    assert roundtrip.status == ApiKeyStatus.ACTIVE.value
    assert roundtrip.prefix == "ak_prefix"
