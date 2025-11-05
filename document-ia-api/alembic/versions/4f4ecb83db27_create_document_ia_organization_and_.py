"""Create document IA organization and apiKey

Revision ID: 4f4ecb83db27
Revises: 19d1c6ddd15d
Create Date: 2025-11-06 09:40:15.168756

"""
import uuid
from typing import Sequence, Union

from alembic import op

from document_ia_api.application.services.api_key.api_key_helper import ApiKeyHelper
from document_ia_api.core.config import api_key_settings
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus

# revision identifiers, used by Alembic.
revision: str = '4f4ecb83db27'
down_revision: Union[str, Sequence[str], None] = '19d1c6ddd15d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Insert default organization without using ORM (works online and with --sql)

    api_key_helper = ApiKeyHelper()

    # noinspection PyProtectedMember
    key_hash, prefix = api_key_helper.get_key_encoding(api_key_settings.DOCUMENT_IA_API_KEY)

    org_id = str(uuid.uuid4())
    op.execute(
        f"""
        INSERT INTO organization (id, name, contact_email, platform_role)
        VALUES ('{org_id}'::uuid, 'Document IA Default Organization', 'nicolas.sagon@beta.gouv.fr', 'PlatformAdmin')
        """
    )

    api_key_id = str(uuid.uuid4())
    op.execute(
        f"""
        INSERT INTO api_key (id, organization_id, key_hash, prefix, status)
        VALUES ('{api_key_id}'::uuid, '{org_id}'::uuid, '{key_hash}', '{prefix}', '{ApiKeyStatus.ACTIVE.value}')
        """
    )


def downgrade() -> None:
    # Remove the inserted default organization by name
    op.execute(
        """
        DELETE
        FROM organization
        WHERE name = 'Document IA Default Organization'
        """
    )
