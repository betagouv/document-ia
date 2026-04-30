from dataclasses import dataclass
from enum import Enum

from document_ia_schemas import SupportedDocumentType


class TaskType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


GENERIC_CLASSIFICATION_MODEL: list[SupportedDocumentType] = [
    SupportedDocumentType.CNI,
    SupportedDocumentType.PASSEPORT,
    SupportedDocumentType.PERMIS_CONDUIRE,
    SupportedDocumentType.AVIS_IMPOSITION,
    SupportedDocumentType.BULLETIN_SALAIRE,
    SupportedDocumentType.VISALE,
    SupportedDocumentType.QUITTANCE_LOYER,
    SupportedDocumentType.FACTURE_ENERGIE,
    SupportedDocumentType.ATTESTATION_CONTRAT_ENERGIE,
]


@dataclass
class PromptConfiguration:
    task_type: TaskType

    def get_template_file(self):
        return f"{self.task_type.value}_agent_system_prompt.md.j2"
