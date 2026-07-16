from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowDTO
from document_ia_worker.core.ocr.deepseek.deepseek_http_ocr_service import (
    DeepSeekHttpHttpOcrService,
)
from document_ia_worker.core.ocr.marker.marker_http_ocr_service import (
    MarkerHttpHttpOcrService,
)
from document_ia_worker.core.ocr.mistral.mistral_http_ocr_service import (
    MistralHttpOcrService,
)
from document_ia_worker.core.ocr.nanonets.nanonets_http_ocr_service import (
    NanonetsHttpHttpOcrService,
)
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step.base_step import BaseStep
from document_ia_worker.workflow.step.download_file.download_file import (
    DownloadFileStep,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_2ddoc_data import (
    ExtractBarcode2DDocData,
)
from document_ia_worker.workflow.step.extract_barcode_data.extract_barcode_data import (
    ExtractBarcodeData,
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


def prepareStepListsV1(
    steps: list[str],
    workflow: WorkflowDTO,
    event_v1: WorkflowExecutionStartedEvent,
    workflow_context: MainWorkflowContext,
    session: AsyncSession,
) -> list[BaseStep[Any]]:
    step_list: list[BaseStep[Any]] = []
    for step in steps:
        if step == "download_file":
            step_list.append(
                DownloadFileStep(
                    workflow_context,
                    event_v1.s3_file_info,
                    event_v1.file_url,
                )
            )
        elif step == "preprocess_file":
            step_list.append(PreprocessFileStep(workflow_context))
        elif step == "extract_content_ocr":
            step_list.append(ExtractContentOcrStep(workflow_context))
        elif step == "extract_content_marker_ocr":
            step_list.append(
                ExtractContentHttpOcrStep(workflow_context, MarkerHttpHttpOcrService())
            )
        elif step == "extract_content_mistral_ocr":
            step_list.append(
                ExtractContentHttpOcrStep(workflow_context, MistralHttpOcrService())
            )
        elif step == "extract_content_nanonets_ocr":
            step_list.append(
                ExtractContentHttpOcrStep(
                    workflow_context, NanonetsHttpHttpOcrService()
                )
            )
        elif step == "extract_content_deepseek_ocr":
            step_list.append(
                ExtractContentHttpOcrStep(
                    workflow_context, DeepSeekHttpHttpOcrService()
                )
            )
        elif step == "extract_barcode_data":
            step_list.append(ExtractBarcodeData())
        elif step == "extract_barcode_raw_data":
            step_list.append(ExtractBarcodeRawData())
        elif step == "extract_barcode_2ddoc_data":
            step_list.append(ExtractBarcode2DDocData())
        elif step == "llm_classify_document":
            step_list.append(
                LLMClassifyDocumentStep(
                    workflow_context,
                    workflow_context.classification_parameters.llm_model
                    if (
                        workflow_context.classification_parameters
                        and workflow_context.classification_parameters.llm_model
                        is not None
                    )
                    else workflow.llm_model,
                )
            )
        elif step == "llm_extract_data":
            step_list.append(
                LLMExtractDocumentStep(
                    workflow_context,
                    workflow_context.extraction_parameters.llm_model
                    if (
                        workflow_context.extraction_parameters
                        and workflow_context.extraction_parameters.llm_model is not None
                    )
                    else workflow.llm_model,
                )
            )
        elif step == "save_workflow_result":
            step_list.append(
                SaveWorkflowResultStep(
                    workflow_context,
                    workflow.id,
                    session,
                )
            )
        else:
            raise Exception(f"Unsupported step: {step}")

    return step_list
