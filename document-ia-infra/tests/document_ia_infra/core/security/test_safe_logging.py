from document_ia_infra.core.model.types.secret import (
    SecretDict,
    SecretPayloadDict,
    SecretPayloadStr,
)
from document_ia_infra.core.security.safe_logging import (
    ALLOWED_PATH_PARAMS,
    ALLOWED_QUERY_PARAMS,
    ALLOWED_REQUEST_HEADERS,
    ALLOWED_RESPONSE_HEADERS,
    ALLOWED_STEP_METADATA_FIELDS,
    extract_safe_host,
    filter_headers,
    filter_path_params,
    filter_query_params,
)
from pydantic import BaseModel, SecretStr


def test_allowed_constants():
    assert "content-type" in ALLOWED_REQUEST_HEADERS
    assert "user-agent" in ALLOWED_REQUEST_HEADERS
    assert "authorization" not in ALLOWED_REQUEST_HEADERS
    assert "cookie" not in ALLOWED_REQUEST_HEADERS

    assert "idempotent-replay" in ALLOWED_RESPONSE_HEADERS
    assert "content-type" in ALLOWED_RESPONSE_HEADERS
    assert "x-request-id" in ALLOWED_RESPONSE_HEADERS

    assert "page" in ALLOWED_QUERY_PARAMS
    assert "limit" in ALLOWED_QUERY_PARAMS
    assert "api_key" not in ALLOWED_QUERY_PARAMS
    assert "token" not in ALLOWED_QUERY_PARAMS

    assert "execution_id" in ALLOWED_PATH_PARAMS
    assert "organization_id" in ALLOWED_PATH_PARAMS

    assert "step_name" in ALLOWED_STEP_METADATA_FIELDS
    assert "user_prompt" not in ALLOWED_STEP_METADATA_FIELDS
    assert "system_prompt" not in ALLOWED_STEP_METADATA_FIELDS
    assert "output_images" not in ALLOWED_STEP_METADATA_FIELDS


def test_filter_headers_case_insensitive_and_strict():
    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": "req-12345",
        "Authorization": "Bearer secret-token",
        "Cookie": "session=sensitive",
        "X-Custom-Secret": "super_secret",
        "Accept": "*/*",
    }
    filtered = filter_headers(headers, ALLOWED_REQUEST_HEADERS)

    assert filtered == {
        "content-type": "application/json",
        "x-request-id": "req-12345",
        "accept": "*/*",
    }
    assert "authorization" not in filtered
    assert "cookie" not in filtered
    assert "x-custom-secret" not in filtered


def test_filter_response_headers():
    headers = {
        "Content-Type": "application/json",
        "Idempotent-Replay": "true",
        "Set-Cookie": "secret_cookie",
        "Server": "uvicorn",
    }
    filtered = filter_headers(headers, ALLOWED_RESPONSE_HEADERS)
    assert filtered == {
        "content-type": "application/json",
        "idempotent-replay": "true",
    }


def test_filter_query_params_masks_unknown():
    params = {
        "limit": 10,
        "offset": 0,
        "api_key": "my_secret_key",
        "token": "sensitive_token",
        "Workflow_Id": "wf-1",
    }
    filtered = filter_query_params(params)

    assert filtered["limit"] == 10
    assert filtered["offset"] == 0
    assert filtered["Workflow_Id"] == "wf-1"
    assert filtered["api_key"] == "**********"
    assert filtered["token"] == "**********"


def test_filter_path_params_retains_only_allowed():
    params = {
        "execution_id": "exec-abc",
        "organization_id": "org-xyz",
        "secret_route_param": "must_be_excluded",
    }
    filtered = filter_path_params(params)

    assert filtered == {
        "execution_id": "exec-abc",
        "organization_id": "org-xyz",
    }
    assert "secret_route_param" not in filtered


def test_extract_safe_host_various_urls():
    # Standard URLs
    assert (
        extract_safe_host("https://subdomain.example.com/path?token=secret#frag")
        == "subdomain.example.com"
    )
    assert (
        extract_safe_host("http://internal-service.local:8080/v1/api")
        == "internal-service.local:8080"
    )
    assert extract_safe_host("https://example.com:443/test") == "example.com"
    assert extract_safe_host("http://example.com:80/test") == "example.com"

    # Userinfo / credentials stripping
    assert (
        extract_safe_host("https://admin:super_secret_password@secure.internal:9000/db")
        == "secure.internal:9000"
    )
    assert (
        extract_safe_host("https://token@api.service.com/webhook") == "api.service.com"
    )

    # Missing scheme
    assert extract_safe_host("example.org/path") == "example.org"
    assert extract_safe_host("localhost:3000/test") == "localhost:3000"

    # None and empty
    assert extract_safe_host(None) == "unknown"
    assert extract_safe_host("") == "unknown"
    assert extract_safe_host("   ") == "unknown"


def test_secret_dict_and_payload():
    d = SecretDict({"api_key": "secret_val", "env": "prod"})
    assert "secret_val" not in str(d)
    assert "secret_val" not in repr(d)
    assert "***" in str(d)
    assert d["api_key"] == "secret_val"
    assert d.get("api_key") == "secret_val"
    assert len(d) == 2
    assert "api_key" in d
    assert d == {"api_key": "secret_val", "env": "prod"}

    class DummyModel(BaseModel):
        secret_str: SecretPayloadStr
        secret_dict: SecretPayloadDict[str]

    model = DummyModel(
        secret_str=SecretStr("supersecret123"),
        secret_dict={"key1": "val1"},  # pyright: ignore[reportArgumentType]
    )

    # String representation masks values
    assert "supersecret123" not in str(model)
    assert "val1" not in str(model)

    # JSON serialization preserves clear values for API response
    json_data = model.model_dump(mode="json")
    assert json_data["secret_str"] == "supersecret123"
    assert json_data["secret_dict"] == {"key1": "val1"}
