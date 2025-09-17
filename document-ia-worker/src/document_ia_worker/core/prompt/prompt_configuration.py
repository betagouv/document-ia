from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


class SupportedDocumentCategory(list[str], Enum):
    IDENTIFICATION = (["cni", "passeport", "permis_conduire"],)
    RESIDENCY = (["residency"],)


@dataclass
class PromptConfiguration:
    task_type: TaskType = TaskType.CLASSIFICATION
    template_file = f"{task_type.value}_agent_system_prompt.md.j2"
