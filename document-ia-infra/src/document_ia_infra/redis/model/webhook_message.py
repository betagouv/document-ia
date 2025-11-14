import json
from dataclasses import dataclass
from uuid import UUID

from document_ia_infra.redis.serializable_message import SerializableMessage


@dataclass
class WebHookMessage(SerializableMessage):
    workflow_execution_id: str
    webhook_id: UUID

    def to_dict(self):
        return {
            "workflow_execution_id": self.workflow_execution_id,
            "webhook_id": str(self.webhook_id),
        }

    @staticmethod
    def from_json(data: str) -> "WebHookMessage":
        obj = json.loads(data)
        return WebHookMessage(
            workflow_execution_id=obj["workflow_execution_id"],
            webhook_id=UUID(obj["webhook_id"]),
        )
