"""Evals callers must honour the safe-logging secret contract types.

`SecretPayloadDict` / `SecretPayloadStr` only serialize in JSON mode and mask
their value in Python mode. The admin UI has to serialize before posting and
unwrap at the one display boundary where the full key must be copyable.
"""

import json
from unittest.mock import patch

import pytest

from document_ia_api.api.contracts.api_key.api_key import APIKeyCreatedResult
from document_ia_api.api.contracts.webhook.webhook import CreateWebHookRequest
from document_ia_evals.services import administration_service as admin

REAL_KEY = "dia_dev_v1_FULLKEYVALUE"


def _created_result() -> APIKeyCreatedResult:
    return APIKeyCreatedResult.model_validate(
        {
            "id": "key-1",
            "prefix": "dia_dev",
            "status": "Active",
            "created_at": "2026-11-12T00:00:00Z",
            "updated_at": "2026-11-12T00:00:00Z",
            "key": REAL_KEY,
        }
    )


def test_python_mode_dump_is_not_json_encodable():
    """Documents the hazard the caller has to avoid."""
    request = CreateWebHookRequest(url="https://example.test/hook")
    with pytest.raises(TypeError):
        json.dumps(request.model_dump())
    # JSON mode is encodable, including with empty headers.
    assert json.loads(json.dumps(request.model_dump(mode="json")))["headers"] == {}


@pytest.mark.parametrize("headers", [{}, {"X-Token": "header-secret"}])
def test_create_webhook_posts_json_serializable_payload(headers):
    request = CreateWebHookRequest(url="https://example.test/hook", headers=headers)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "hook-1",
                "organization_id": "00000000-0000-0000-0000-000000000001",
                "url": "https://example.test/hook",
                "headers": headers,
                "created_at": "2026-11-12T00:00:00Z",
                "updated_at": "2026-11-12T00:00:00Z",
            }

    def fake_post(url, headers=None, json=None):
        # requests would raise here if the payload were not JSON-encodable.
        captured["payload"] = json
        captured["encoded"] = __import__("json").dumps(json)
        return FakeResponse()

    with patch.object(admin.requests, "post", side_effect=fake_post):
        with patch.object(admin, "_get_headers", return_value={}):
            with patch.object(admin, "_get_url", return_value="https://api.test/hook"):
                admin.create_webhook("org-1", request)

    assert json.loads(captured["encoded"])["headers"] == headers


def test_created_key_dialog_displays_the_full_key():
    """The one-time copy dialog must not show the masked representation."""
    from document_ia_evals.pages import administration

    result = _created_result()
    shown: list = []

    with patch.object(administration.st, "code", side_effect=lambda v, **k: shown.append(v)):
        with patch.object(administration.st, "success"), patch.object(
            administration.st, "write"
        ), patch.object(administration.st, "button", return_value=False):
            administration._show_created_api_key_dialog.__wrapped__(result)

    assert shown == [REAL_KEY]
    assert str(result.key) not in shown  # masked form must not be displayed


def test_key_stays_masked_outside_the_display_boundary():
    """Unwrapping is local to the dialog; the contract type still masks."""
    result = _created_result()
    assert str(result.key) == "**********"
    assert REAL_KEY not in repr(result)
