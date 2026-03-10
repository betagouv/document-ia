from datetime import datetime, timezone
from uuid import uuid4

from document_ia_infra.data.organization.entity.organization import OrganizationEntity
from document_ia_infra.data.organization.enum.platform_role import PlatformRole
from document_ia_infra.data.organization.mapper.organization_mapper import (
    entity_to_dto,
    dto_to_entity,
    entities_to_dtos,
)


def test_entity_to_dto_and_back():
    org_id = uuid4()
    now = datetime.now(timezone.utc)

    entity = OrganizationEntity(
        id=org_id,
        contact_email="contact@example.com",
        name="Acme Corp",
        platform_role=PlatformRole.PLATFORM_ADMIN.value,
        created_at=now,
        updated_at=now,
    )

    dto = entity_to_dto(entity)
    assert dto.id == org_id
    assert dto.contact_email == "contact@example.com"
    assert dto.name == "Acme Corp"
    assert dto.platform_role == PlatformRole.PLATFORM_ADMIN
    assert dto.created_at == now

    roundtrip = dto_to_entity(dto)
    assert roundtrip.id == entity.id
    assert roundtrip.platform_role == PlatformRole.PLATFORM_ADMIN.value


def test_entities_to_dtos_list():
    now = datetime.now(timezone.utc)
    e1 = OrganizationEntity(id=uuid4(), contact_email="a@x.com", name="A", platform_role=PlatformRole.STANDARD.value, created_at=now, updated_at=now)
    e2 = OrganizationEntity(id=uuid4(), contact_email="b@x.com", name="B", platform_role=PlatformRole.PLATFORM_ADMIN.value, created_at=now, updated_at=now)

    dtos = entities_to_dtos([e1, e2])
    assert len(dtos) == 2
    assert dtos[0].name == "A"
    assert dtos[1].platform_role == PlatformRole.PLATFORM_ADMIN
