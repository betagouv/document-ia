import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from document_ia_infra.data.data_settings import database_settings
from document_ia_infra.service.webhook_encryption_service import (
    WebhookEncryptionService,
)


@pytest.fixture
def fernet_key() -> str:
    # Fernet.generate_key() returns URL-safe base64-encoded 32-byte key (bytes)
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def service_with_key(monkeypatch: pytest.MonkeyPatch, fernet_key: str) -> WebhookEncryptionService:
    # Injecte une clé dans les settings puis instancie le service
    monkeypatch.setattr(
        database_settings,
        "WEBHOOK_SECRET_ENCRYPTION_KEY",
        SecretStr(fernet_key),
        raising=True,
    )
    return WebhookEncryptionService()


def test_encrypt_then_decrypt_roundtrip(service_with_key: WebhookEncryptionService):
    data = {"X-Signature": "abc123", "X-Event": "document.completed", "n": "é"}

    token = service_with_key.encrypt_headers(data)
    assert isinstance(token, str) and len(token) > 0

    restored = service_with_key.decrypt_headers(token)
    assert restored == data


def test_decrypt_none_returns_empty_dict(service_with_key: WebhookEncryptionService):
    # encrypted_data=None doit retourner {} quand la clé est présente
    assert service_with_key.decrypt_headers(None) == {}


def test_encrypt_raises_without_key(monkeypatch: pytest.MonkeyPatch):
    # Supprime la clé puis instancie le service
    monkeypatch.setattr(
        database_settings, "WEBHOOK_SECRET_ENCRYPTION_KEY", None, raising=True
    )
    svc = WebhookEncryptionService()

    with pytest.raises(ValueError, match="Encryption key is not set"):
        _ = svc.encrypt_headers({"k": "v"})


def test_decrypt_raises_without_key(monkeypatch: pytest.MonkeyPatch):
    # Supprime la clé puis instancie le service
    monkeypatch.setattr(
        database_settings, "WEBHOOK_SECRET_ENCRYPTION_KEY", None, raising=True
    )
    svc = WebhookEncryptionService()

    with pytest.raises(ValueError, match="Encryption key is not set"):
        _ = svc.decrypt_headers("anything")


def test_decrypt_with_wrong_key_raises(
        monkeypatch: pytest.MonkeyPatch, fernet_key: str
):
    # Service A chiffre avec la bonne clé
    monkeypatch.setattr(
        database_settings,
        "WEBHOOK_SECRET_ENCRYPTION_KEY",
        SecretStr(fernet_key),
        raising=True,
    )
    svc_a = WebhookEncryptionService()
    token = svc_a.encrypt_headers({"a": "1"})

    # Service B tente de déchiffrer avec une autre clé (échec attendu)
    other_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(
        database_settings,
        "WEBHOOK_SECRET_ENCRYPTION_KEY",
        SecretStr(other_key),
        raising=True,
    )
    svc_b = WebhookEncryptionService()

    with pytest.raises(InvalidToken):
        _ = svc_b.decrypt_headers(token)
