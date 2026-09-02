from pydantic import SecretStr
from requests import PreparedRequest

from document_ia_infra.core.loki_settings import (
    LokiBearerAuth,
    LoggingSettings,
    build_loki_auth,
)


def test_build_loki_auth_returns_none_without_token() -> None:
    assert build_loki_auth(None) is None
    assert build_loki_auth(SecretStr("")) is None
    assert build_loki_auth(SecretStr("   ")) is None


def test_build_loki_auth_returns_bearer_auth() -> None:
    auth = build_loki_auth(SecretStr("my-token"))
    assert isinstance(auth, LokiBearerAuth)
    assert auth.token == "my-token"


def test_loki_bearer_auth_sets_authorization_header() -> None:
    request = PreparedRequest()
    request.prepare(method="POST", url="https://loki.example/loki/api/v1/push")

    result = LokiBearerAuth("my-token")(request)

    assert result.headers["Authorization"] == "Bearer my-token"


def test_logging_settings_reads_bearer_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOKI_BEARER_TOKEN", "env-token")

    settings = LoggingSettings(_env_file=None)

    assert settings.LOKI_BEARER_TOKEN is not None
    assert settings.LOKI_BEARER_TOKEN.get_secret_value() == "env-token"
