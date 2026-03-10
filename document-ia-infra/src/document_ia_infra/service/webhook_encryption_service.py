import json
from typing import Optional

from cryptography.fernet import Fernet
from document_ia_infra.data.data_settings import database_settings


class WebhookEncryptionService:
    def __init__(self):
        self.encryption_key = database_settings.WEBHOOK_SECRET_ENCRYPTION_KEY

    def encrypt_headers(self, data: dict[str, str]) -> str:
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if self.encryption_key is None:
            raise ValueError("Encryption key is not set.")
        key = self.encryption_key.get_secret_value().encode()
        f = Fernet(key)
        token = f.encrypt(json_str.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt_headers(self, encrypted_data: Optional[str]) -> dict[str, str]:
        if self.encryption_key is None:
            raise ValueError("Encryption key is not set.")
        if encrypted_data is None:
            return {}
        key = self.encryption_key.get_secret_value().encode()
        f = Fernet(key)
        decrypted_bytes = f.decrypt(encrypted_data.encode("utf-8"))
        decrypted_str = decrypted_bytes.decode("utf-8")
        return json.loads(decrypted_str)


webhook_encryption_service = WebhookEncryptionService()
