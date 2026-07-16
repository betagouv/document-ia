from typing import List, Union, Literal, Annotated, Optional

from pydantic import BaseModel, Field, model_validator

from document_ia_infra.data.workflow.dto.enums import (
    BarcodeExtractionType,
    OCRModel,
    LLMModel,
)
from document_ia_schemas import SupportedDocumentType


class BarcodeParams(BaseModel):
    barcode_type: BarcodeExtractionType = Field(
        default=BarcodeExtractionType.TWO_D_DOC,
        description="Type d'extraction de données de code-barres",
    )


class OCRParams(BaseModel):
    model: OCRModel = Field(
        default=OCRModel.MISTRAL,
        description="Modèle OCR à utiliser pour l'extraction de contenu textuel",
    )


class LLMClassifyParams(BaseModel):
    model: LLMModel = Field(
        default=LLMModel.ALBERT_LARGE,
        description="Modèle LLM à utiliser pour l'inférence de classification",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Température à utiliser pour la classification (entre 0.0 et 1.0)",
    )
    # Accepte la string "all" OU une liste de DocumentType
    document_types: Union[Literal["all"], List[SupportedDocumentType]] = Field(
        default="all",
        description="Type(s) de document à utiliser pour la classification (ex : cni, passeport, etc.)",
    )


class LLMExtractParams(BaseModel):
    model: LLMModel = Field(
        default=LLMModel.ALBERT_LARGE,
        description="Modèle LLM à utiliser pour l'inférence de l'extraction",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Température à utiliser pour l'extraction (entre 0.0 et 1.0)",
    )
    # Optionnel ici: une validation au niveau WorkflowV2Dto l'impose
    # quand aucune étape de classification ne précède l'extraction.
    document_type: Optional[SupportedDocumentType] = Field(
        default=None,
        description="Type de document à utiliser pour l'extraction (ex : cni, passeport, etc.)",
    )


# ==========================================
# 3. DÉFINITION DES ACTIONS (Discriminated Union)
# ==========================================


class BaseWorkflowStepDto(BaseModel):
    # Base class for shared step behavior; each concrete step defines its own
    # discriminant `action` literal for Pydantic union dispatch.
    pass


class DownloadFileStepDto(BaseWorkflowStepDto):
    action: Literal["download_file"]


class PreprocessFileStepDto(BaseWorkflowStepDto):
    action: Literal["preprocess_file"]


class SaveWorkflowResultStepDto(BaseWorkflowStepDto):
    action: Literal["save_workflow_result"]


class ExtractBarcodeDataStepDto(BaseWorkflowStepDto):
    action: Literal["extract_barcode_data"]
    params: BarcodeParams


class ExtractContentOcrStepDto(BaseWorkflowStepDto):
    action: Literal["extract_content_ocr"]
    params: OCRParams


class LlmClassifyDocumentStepDto(BaseWorkflowStepDto):
    action: Literal["llm_classify_document"]
    params: LLMClassifyParams


class LlmExtractDataStepDto(BaseWorkflowStepDto):
    action: Literal["llm_extract_data"]
    params: LLMExtractParams


WorkflowStep = Annotated[
    Union[
        DownloadFileStepDto,
        PreprocessFileStepDto,
        ExtractBarcodeDataStepDto,
        ExtractContentOcrStepDto,
        LlmClassifyDocumentStepDto,
        LlmExtractDataStepDto,
        SaveWorkflowResultStepDto,
    ],
    Field(discriminator="action"),
]


class WorkflowV2Dto(BaseModel):
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    supported_file_types: List[str]
    max_file_size_mb: int
    processing_timeout_minutes: int
    steps: List[WorkflowStep]

    @model_validator(mode="after")
    def validate_extract_step_document_type_dependency(self):
        for idx, step in enumerate(self.steps):
            if not isinstance(step, LlmExtractDataStepDto):
                continue

            if step.params.document_type is not None:
                continue

            has_prior_classification = any(
                isinstance(previous_step, LlmClassifyDocumentStepDto)
                for previous_step in self.steps[:idx]
            )

            if not has_prior_classification:
                raise ValueError(
                    "llm_extract_data.params.document_type is required when no prior llm_classify_document step exists"
                )

        return self


class WorkflowsConfigDto(BaseModel):
    workflows: List[WorkflowV2Dto]
