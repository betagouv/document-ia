from dataclasses import dataclass, asdict

from document_ia_redis.serializable_message import SerializableMessage


@dataclass
class WorkflowExecutionMessage(SerializableMessage):
    workflow_execution_id: str

    def to_dict(self):
        return asdict(self)
