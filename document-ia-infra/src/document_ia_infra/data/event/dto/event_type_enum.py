from enum import Enum


class EventType(str, Enum):
    WORKFLOW_EXECUTION_STARTED = "WorkflowExecutionStarted"
    WORKFLOW_EXECUTION_COMPLETED = "WorkflowExecutionCompleted"
    WORKFLOW_EXECUTION_FAILED = "WorkflowExecutionFailed"
    WORKFLOW_EXECUTION_STEP_COMPLETED = "WorkflowExecutionStepCompleted"

    @classmethod
    def from_str(cls, value: str) -> "EventType":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"Unknown event type: {value}")

    def __str__(self) -> str:
        return self.value
