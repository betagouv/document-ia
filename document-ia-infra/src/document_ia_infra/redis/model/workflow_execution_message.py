import json
from dataclasses import dataclass, asdict

from document_ia_infra.redis.serializable_message import SerializableMessage


@dataclass
class WorkflowExecutionMessage(SerializableMessage):
    workflow_execution_id: str

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_json(data: str) -> "WorkflowExecutionMessage":
        obj = json.loads(data)
        return WorkflowExecutionMessage(**obj)
