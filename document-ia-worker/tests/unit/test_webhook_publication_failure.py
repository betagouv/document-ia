"""Notification des webhooks lorsque la publication Redis échoue (issue #120).

Le publisher lève désormais `PublishFailedError` au lieu de renvoyer `None`.
Une indisponibilité doit rester isolée à chaque webhook : les notifications
suivantes doivent toujours être tentées.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from document_ia_infra.redis.publisher import PublishFailedError
from document_ia_worker.workflow.workflow_manager import WorkflowManager


@pytest.mark.asyncio
async def test_webhook_fanout_continues_after_a_publication_failure():
    """Un échec sur le premier webhook n'abandonne pas les suivants."""
    first_webhook_id = uuid4()
    second_webhook_id = uuid4()

    with patch(
        "document_ia_worker.workflow.workflow_manager.WebHookRepository"
    ) as repository_class:
        repository = repository_class.return_value
        repository.list_webhooks_by_organization = AsyncMock(
            return_value=[
                MagicMock(id=first_webhook_id),
                MagicMock(id=second_webhook_id),
            ]
        )

        manager = WorkflowManager.__new__(WorkflowManager)
        manager.main_workflow_context = MagicMock(
            execution_id="exec-fanout", organization_id=uuid4()
        )
        manager._webhook_producer = MagicMock()
        # Le premier appel échoue, le second aboutirait : les deux doivent
        # effectivement être tentés.
        manager._webhook_producer.publish_message = AsyncMock(
            side_effect=[
                PublishFailedError("webhook_stream", "no_connection"),
                "2-0",
            ]
        )

        await manager._notify_webhook_execution_finished(AsyncMock())

        assert manager._webhook_producer.publish_message.await_count == 2
        notified_webhooks = [
            call.args[0].webhook_id
            for call in manager._webhook_producer.publish_message.await_args_list
        ]
        assert notified_webhooks == [first_webhook_id, second_webhook_id]
