import base64
import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher

from document_ia_api.core.config import api_key_settings
from document_ia_infra.data.api_key.dto.api_key_dto import ApiKeyDTO


class ApiKeyHelper:
    def __init__(self):
        self.ph = PasswordHasher(time_cost=2, memory_cost=1024 * 64, parallelism=4)
        self.key_re = re.compile(
            r"^dia_(dev|staging|prod)_(v?\d+)_[A-Z2-7]{8}_[A-Z2-7]{40,64}_[A-Z2-7]{4}$"
        )

        pass

    def generate_new_api_key(self) -> tuple[str, str, str, str]:
        """Generates a new API key."""
        raw = secrets.token_bytes(32)
        body = self._b32_no_pad(raw)
        prefix = body[:8]
        chk = self._hmac_b32(api_key_settings.API_KEY_PEPPER_CHK, body)[:4]
        presented = f"dia_{api_key_settings.API_KEY_ENV}_{api_key_settings.API_KEY_VERSION}_{prefix}_{body}_{chk}"
        mac = hmac.new(
            api_key_settings.API_KEY_PEPPER_HASH.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        key_hash = self.ph.hash(mac)
        return presented, prefix, chk, key_hash

    def verify_api_key(self, presented: str, api_key_dto: ApiKeyDTO) -> bool:
        if not self.key_re.match(presented):
            return False

        _, _env, _version, prefix, body, chk = presented.split("_", 5)

        expected_chk = self._hmac_b32(api_key_settings.API_KEY_PEPPER_CHK, body)[:4]
        if not hmac.compare_digest(expected_chk, chk):
            return False

        if prefix != api_key_dto.prefix:
            return False

        mac = hmac.new(
            api_key_settings.API_KEY_PEPPER_HASH.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        try:
            ok = self.ph.verify(api_key_dto.key_hash, mac)
            return ok
        except Exception:
            return False

    def get_key_encoding(self, presented: str) -> tuple[str, str]:
        """This method is used for initialization of the database with an api key present in .env file.
        - Validates format and checksum
        - Computes the MAC hash and Argon2 hash for storage
        """
        if not self.key_re.match(presented):
            raise ValueError("Invalid API key format")

        _, _env, _version, prefix, body, chk = presented.split("_", 5)

        expected_chk = self._hmac_b32(api_key_settings.API_KEY_PEPPER_CHK, body)[:4]
        if not hmac.compare_digest(expected_chk, chk):
            raise ValueError("Invalid API key checksum")

        mac = hmac.new(
            api_key_settings.API_KEY_PEPPER_HASH.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        key_hash = self.ph.hash(mac)

        return key_hash, prefix

    def get_key_prefix(self, presented: str) -> str:
        """Extracts the prefix from the presented API key."""
        if not self.key_re.match(presented):
            raise ValueError("Invalid API key format")

        _, _env, _version, prefix, _, _ = presented.split("_", 5)
        return prefix

    def _b32_no_pad(self, data: bytes) -> str:
        """Encodes bytes to base32 without padding."""

        return base64.b32encode(data).decode("ascii").rstrip("=").upper()

    def _hmac_b32(self, pepper: str, msg: str) -> str:
        d = hmac.new(pepper.encode(), msg.encode(), hashlib.sha256).digest()
        return self._b32_no_pad(d)
