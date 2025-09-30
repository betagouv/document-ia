from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


class SupportedDocumentType(str, Enum):
    CNI = "cni"
    PASSEPORT = "passeport"
    PERMIS_CONDUIRE = "permis_conduire"

    @staticmethod
    def from_str(label: str) -> "SupportedDocumentType":
        label = label.lower()
        try:
            return SupportedDocumentType(label)
        except ValueError:
            raise ValueError(f"Unknown SupportedDocumentType: {label}")


@dataclass
class PromptConfiguration:
    task_type: TaskType

    def get_template_file(self):
        return f"{self.task_type.value}_agent_system_prompt.md.j2"
