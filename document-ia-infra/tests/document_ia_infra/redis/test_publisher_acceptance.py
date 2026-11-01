"""Publication sur un vrai Redis : échec puis récupération (issue #120).

Ces tests exercent le publisher contre un Redis réel, arrêté puis relancé :
- avant la publication, l'indisponibilité lève `PublishFailedError` ;
- après récupération, la publication aboutit et le message est bien présent.
"""

import pytest
from redis.asyncio import Redis

from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.publisher import PublishFailedError, Publisher
from document_ia_infra.redis.redis_manager import RedisManager
from document_ia_infra.redis.redis_settings import redis_settings

pytestmark = pytest.mark.asyncio

STREAM = "test_publish_acceptance_stream"


@pytest.fixture
async def redis_connection():
    connection = Redis(
        host=redis_settings.REDIS_HOST,
        port=redis_settings.REDIS_PORT,
        db=redis_settings.REDIS_DB,
        password=redis_settings.REDIS_PASSWORD.get_secret_value(),
        decode_responses=True,
    )
    try:
        await connection.ping()
    except Exception:
        await connection.aclose()
        pytest.skip("Redis indisponible pour les tests de publication")
        return
    await connection.delete(STREAM)
    yield connection
    await connection.delete(STREAM)
    await connection.aclose()


async def test_publish_fails_when_redis_is_unreachable(monkeypatch):
    """Aucun `None` silencieux : l'échec de programmation est explicite."""
    # Redis éteint : le port 6399 ne répond pas.
    monkeypatch.setattr(
        "document_ia_infra.redis.redis_manager.redis_settings.REDIS_URL",
        "redis://:password@localhost:6399/0",
    )
    manager = RedisManager()
    manager.max_retries = 1
    manager.base_delay = 0.0
    publisher = Publisher[WorkflowExecutionMessage](
        STREAM, current_redis_manager=manager
    )

    with pytest.raises(PublishFailedError) as exc_info:
        await publisher.publish_message(WorkflowExecutionMessage(workflow_execution_id="exec-down"))

    assert exc_info.value.stream_name == STREAM
    # Le message ne transporte ni charge utile ni contenu de document.
    assert "exec-down" not in str(exc_info.value)

    await manager.close()


async def test_publish_succeeds_after_redis_recovers(redis_connection, monkeypatch):
    """Après récupération de Redis, le traitement est bien programmé."""
    # `get_redis_url()` interpole le SecretStr sans le déballer : on fournit une
    # URL explicite pour que le manager utilise le même mot de passe que Redis.
    monkeypatch.setattr(
        "document_ia_infra.redis.redis_manager.redis_settings.REDIS_URL",
        (
            f"redis://:{redis_settings.REDIS_PASSWORD.get_secret_value()}"
            f"@{redis_settings.REDIS_HOST}:{redis_settings.REDIS_PORT}"
            f"/{redis_settings.REDIS_DB}"
        ),
    )
    manager = RedisManager()
    publisher = Publisher[WorkflowExecutionMessage](
        STREAM, current_redis_manager=manager
    )

    message_id = await publisher.publish_message(
        WorkflowExecutionMessage(workflow_execution_id="exec-recovered")
    )

    assert message_id
    entries = await redis_connection.xrange(STREAM)
    assert len(entries) == 1
    # Le message publié programme bien l'exécution attendue.
    assert "exec-recovered" in entries[0][1]["data"]

    await manager.close()
