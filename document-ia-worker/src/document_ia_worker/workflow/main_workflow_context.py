from dataclasses import dataclass
from datetime import datetime


@dataclass
class MainWorkflowContext:
    execution_id: str
    start_time: float = datetime.now().timestamp()
    number_of_step_executed: int = 0
