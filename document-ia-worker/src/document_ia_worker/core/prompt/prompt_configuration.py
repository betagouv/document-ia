from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


class SupportedDocumentType(str, Enum):
    CNI = "cni"
    PASSEPORT = "passeport"
    PERMIS_CONDUIRE = "permis_conduire"


@dataclass
class PromptConfiguration:
    task_type: TaskType = TaskType.CLASSIFICATION
    template_file = f"{task_type.value}_agent_system_prompt.md.j2"
