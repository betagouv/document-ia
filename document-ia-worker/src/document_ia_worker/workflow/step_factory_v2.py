import logging
from typing import Any

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.workflow.dto.enums import BarcodeExtractionType
from document_ia_infra.data.workflow.dto.enums import OCRModel
from document_ia_infra.data.workflow.dto.workflow_v2_dto import BarcodeParams
from document_ia_infra.data.workflow.dto.workflow_v2_dto import DownloadFileStepDto
from document_ia_infra.data.workflow.dto.workflow_v2_dto import (
    ExtractBarcodeDataStepDto,
)
from document_ia_infra.data.workflow.dto.workflow_v2_dto import ExtractContentOcrStepDto
from document_ia_infra.data.workflow.dto.workflow_v2_dto import LLMClassifyParams
from document_ia_infra.data.workflow.dto.workflow_v2_dto import (
    LlmClassifyDocumentStepDto,
)
from document_ia_infra.data.workflow.dto.workflow_v2_dto import LLMExtractParams
from document_ia_infra.data.workflow.dto.workflow_v2_dto import LlmExtractDataStepDto
from document_ia_infra.data.workflow.dto.workflow_v2_dto import OCRParams
from document_ia_infra.data.workflow.dto.workflow_v2_dto import PreprocessFileStepDto
from document_ia_infra.data.workflow.dto.workflow_v2_dto import PreprocessFileParams
from document_ia_infra.data.workflow.dto.workflow_v2_dto import (
    SaveWorkflowResultStepDto,
)
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowStep
from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_worker.core.ocr.mistral.mistral_http_ocr_service import (
    MistralHttpOcrService,
)
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    ExtractBarcode2DDocData,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_raw_data import (
    ExtractBarcodeRawData,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_http_ocr import (
    ExtractContentHttpOcrStep,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr import (
    ExtractContentOcrStep,
)
from document_ia_worker.workflow.step.extract_content_ocr.extract_content_ocr_light_on import (
    ExtractContentOcrLightOnStep,
)
from document_ia_worker.workflow.step.llm_classify_document.llm_classify_document import (
    LLMClassifyDocumentStep,
)
from document_ia_worker.workflow.step.llm_extract_document.llm_extract_document import (
    LLMExtractDocumentStep,
)
from document_ia_worker.workflow.step.preprocess_file.preprocess_file import (
    PreprocessFileStep,
)
from document_ia_worker.workflow.step.save_workflow_result.save_workflow_result import (
    SaveWorkflowResultStep,
)

logger = logging.getLogger(__name__)


def prepareStepListsV2(
    event_v2: WorkflowExecutionStartedEvent,
    workflow_context: MainWorkflowContext,
    session: AsyncSession,
) -> list[BaseStep[Any]]:
    step_list: list[BaseStep[Any]] = []

    if event_v2.workflow_configuration is None:
        raise Exception("Workflow configuration is missing")

    workflow_configuration: WorkflowV2Dto = event_v2.workflow_configuration

    for step in workflow_configuration.steps:
        typed_step: WorkflowStep = step  # explicite pour le checker
        match typed_step.action:
            case "download_file":
                assert isinstance(typed_step, DownloadFileStepDto)
                step_list.append(build_download_step(workflow_context, event_v2))
            case "preprocess_file":
                assert isinstance(typed_step, PreprocessFileStepDto)
                step_list.append(
                    build_preprocess_file_step(workflow_context, typed_step.params)
                )
            case "extract_barcode_data":
                assert isinstance(typed_step, ExtractBarcodeDataStepDto)
                step_list.append(build_extract_barcode_data_step(typed_step.params))
            case "extract_content_ocr":
                assert isinstance(typed_step, ExtractContentOcrStepDto)
                step_list.append(
                    build_extract_content_ocr_step(workflow_context, typed_step.params)
                )
            case "llm_classify_document":
                assert isinstance(typed_step, LlmClassifyDocumentStepDto)
                step_list.append(
                    build_llm_classify_step(workflow_context, typed_step.params)
                )
            case "llm_extract_data":
                assert isinstance(typed_step, LlmExtractDataStepDto)
                step_list.append(
                    build_llm_extract_step(workflow_context, typed_step.params)
                )
            case "save_workflow_result":
                assert isinstance(typed_step, SaveWorkflowResultStepDto)
                step_list.append(
                    build_save_workflow_result(
                        workflow_context, event_v2.workflow_id, session
                    )
                )
            case _:
                raise Exception(f"Unsupported step: {typed_step.action}")
    return step_list


def build_download_step(
    workflow_context: MainWorkflowContext, event_v2: WorkflowExecutionStartedEvent
) -> DownloadFileStep:
    return DownloadFileStep(
        workflow_context,
        event_v2.s3_file_info,
        event_v2.file_url,
    )


def build_preprocess_file_step(
    workflow_context: MainWorkflowContext,
    step_params: PreprocessFileParams,
) -> PreprocessFileStep:
    return PreprocessFileStep(
        workflow_context,
        params=step_params,
    )


def build_extract_barcode_data_step(step_params: BarcodeParams) -> BaseStep[Any]:
    match step_params.barcode_type:
        case BarcodeExtractionType.TWO_D_DOC:
            return ExtractBarcode2DDocData()
        case BarcodeExtractionType.RAW:
            return ExtractBarcodeRawData()
        case _:
            raise ValueError(f"Unknown barcode type: {step_params.barcode_type}")


def build_extract_content_ocr_step(
    workflow_context: MainWorkflowContext, step_params: OCRParams
) -> BaseStep[Any]:
    match step_params.model:
        case OCRModel.TESSERACT:
            return ExtractContentOcrStep(workflow_context)
        case OCRModel.MISTRAL:
            return ExtractContentHttpOcrStep(workflow_context, MistralHttpOcrService())
        case OCRModel.LIGHT_ON:
            return ExtractContentOcrLightOnStep(workflow_context)
        case _:
            raise ValueError(f"Unknown OCR model: {step_params.model}")


def build_save_workflow_result(
    workflow_context: MainWorkflowContext, workflow_id: str, session: AsyncSession
) -> SaveWorkflowResultStep:
    return SaveWorkflowResultStep(
        workflow_context,
        workflow_id,
        session,
    )


def build_llm_classify_step(
    workflow_context: MainWorkflowContext, step_params: LLMClassifyParams
) -> LLMClassifyDocumentStep:
    return LLMClassifyDocumentStep.from_v2_params(
        main_workflow_context=workflow_context,
        params=step_params,
    )


def build_llm_extract_step(
    workflow_context: MainWorkflowContext, step_params: LLMExtractParams
) -> LLMExtractDocumentStep:
    return LLMExtractDocumentStep.from_v2_params(
        main_workflow_context=workflow_context,
        params=step_params,
    )
