import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from document_ia_infra.openai import openai_manager as module


class Response(BaseModel):
    value: int


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_request_owns_client_on_same_loop(monkeypatch, outcome):
    loop = asyncio.get_running_loop()
    created = []
    entered = asyncio.Event()
    closed_on = []

    class Client:
        def __init__(self, **_kwargs):
            created.append(asyncio.get_running_loop())
            self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            await self.close()

        async def close(self):
            closed_on.append(asyncio.get_running_loop())

        async def parse(self, **_kwargs):
            entered.set()
            if outcome == "error":
                raise RuntimeError("request failed")
            if outcome == "cancel":
                await asyncio.Event().wait()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='{"value": 1}'))
                ]
            )

    monkeypatch.setattr(module, "AsyncOpenAI", Client)
    monkeypatch.setattr(
        module.tiktoken,
        "encoding_for_model",
        lambda _model: SimpleNamespace(encode=lambda text: list(text)),
    )
    manager = module.OpenAIManager()
    assert created == []  # Unused/skipped steps never allocate a client.
    request = asyncio.create_task(
        manager.get_classification_response("system", "user", Response, "model")
    )
    await entered.wait()
    if outcome == "cancel":
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
    elif outcome == "error":
        with pytest.raises(RuntimeError, match="request failed"):
            await request
    else:
        response, *_ = await request
        assert response.value == 1
    assert created == [loop]
    assert closed_on == [loop]
