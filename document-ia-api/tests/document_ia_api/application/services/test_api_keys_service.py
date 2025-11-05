import uuid
from datetime import datetime

from document_ia_api.application.services.api_key.api_key_helper import ApiKeyHelper
from document_ia_api.core.config import api_key_settings
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO
from document_ia_infra.data.api_key.enum.api_key_status import ApiKeyStatus


def test_generate_and_verify_api_key():
    api_key_helper = ApiKeyHelper()

    presented, prefix, chk, key_hash = api_key_helper.generate_new_api_key()

    assert isinstance(presented, str) and presented
    assert isinstance(prefix, str) and len(prefix) == 8
    assert isinstance(chk, str) and len(chk) == 4
    assert isinstance(key_hash, str) and key_hash

    # Regex should match the generated key
    assert api_key_helper.key_re.match(presented) is not None

    # Check that ENV and VERSION are present in the string
    assert f"dia_{api_key_settings.API_KEY_ENV}_{api_key_settings.API_KEY_VERSION}_" in presented

def test_verify_api_key_with_valid_key():
    api_key_helper = ApiKeyHelper()
    checked_api_key = "dia_dev_1_WMBUIIAK_WMBUIIAK2QQFKWQ5S7YPQZIUTFHQ2KKNFKPESOLLCQVME2NJFZUQ_BYMQ"
    record = ApiKeyDTO(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        organization=None,
        key_hash="$argon2id$v=19$m=65536,t=2,p=4$dag2me5gKU9k/N65qZm1lA$edWO9fTYKHBSVbRmV3MnVGdIUPf1ULk+6gJZ66pWjgk",
        prefix="WMBUIIAK",
        status=ApiKeyStatus.ACTIVE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    is_valid = api_key_helper.verify_api_key(checked_api_key, record)

    assert isinstance(is_valid, bool) and is_valid

def test_verify_api_key_with_invalid_key():
    api_key_helper = ApiKeyHelper()
    checked_api_key = "dia_dev_1_WMBUIIAK_WMBUIIAK2AAFKWQ5S7YPQZIUTFHQ2KKNFKPESOLLCQVME2NJFZUQ_BYMQ"
    record = ApiKeyDTO(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        organization=None,
        key_hash="$argon2id$v=19$m=65536,t=2,p=4$dag2me5gKU9k/N65qZm1lA$edWO9fTYKHBSVbRmV3MnVGdIUPf1ULk+6gJZ66pWjgk",
        prefix="WMBUIIAK",
        status=ApiKeyStatus.ACTIVE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    is_valid = api_key_helper.verify_api_key(checked_api_key, record)

    assert isinstance(is_valid, bool) and not is_valid

def test_internal_get_key_encoding():
    api_key_helper = ApiKeyHelper()
    presented = "dia_dev_1_ID5RKLRX_ID5RKLRXQZM52XFUNGUHOBL7MAU3XQDRYN3R4HZH24DGGTFROBLA_5YTN"

    _, _env, _version, prefix, body, chk = presented.split("_", 5)

    key_hash, prefix = api_key_helper.get_key_encoding(presented)

    record = ApiKeyDTO(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        organization=None,
        key_hash=key_hash,
        prefix=prefix,
        status=ApiKeyStatus.ACTIVE,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    is_valid = api_key_helper.verify_api_key(presented, record)

    assert isinstance(is_valid, bool) and is_valid
