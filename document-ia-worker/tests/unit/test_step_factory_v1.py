from datetime import datetime, UTC
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
    WorkflowExecutionStartedEvent,
)
from document_ia_infra.data.workflow.dto.enums import LLMModel
from document_ia_infra.data.workflow.dto.workflow_dto import WorkflowDTO
from document_ia_schemas import SupportedDocumentType
from document_ia_worker.workflow.main_workflow_context import MainWorkflowContext
from document_ia_worker.workflow.step_factory_v1 import prepareStepListsV1


def _build_workflow(steps: list[str]) -> WorkflowDTO:
    return WorkflowDTO(
        id="wf-test",
        name="Workflow test",
        description="Workflow test",
        version="1.0.0",
        enabled=True,
        supported_file_types=["application/pdf"],
        steps=steps,
        llm_model=LLMModel.ALBERT_LARGE,
        max_file_size_mb=25,
        processing_timeout_minutes=5,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _build_event(version: int = 1) -> WorkflowExecutionStartedEvent:
    return WorkflowExecutionStartedEvent(
        workflow_id="wf-test",
        execution_id="exec-1",
        organization_id=uuid4(),
        created_at=datetime.now(UTC),
        version=version,
        metadata={},
        file_url="https://example.com/document.pdf",
        classification_parameters=ClassificationParameters(
            llm_model=LLMModel.ALBERT_SMALL
        ),
        extraction_parameters=ExtractionParameters(
            llm_model=LLMModel.OPEN_WEIGHT_SMALL,
            document_type=SupportedDocumentType.CNI,
        ),
    )


def _build_context() -> MainWorkflowContext:
    return MainWorkflowContext(
        execution_id="exec-1",
        start_time=datetime.now(UTC),
        organization_id=uuid4(),
        classification_parameters=ClassificationParameters(
            llm_model=LLMModel.ALBERT_SMALL
        ),
        extraction_parameters=ExtractionParameters(
            llm_model=LLMModel.OPEN_WEIGHT_SMALL,
            document_type=SupportedDocumentType.CNI,
        ),
        steps_metadata=[],
    )


def test_prepare_step_lists_v1_creates_all_supported_steps():
    steps = [
        "download_file",
        "preprocess_file",
        "extract_content_ocr",
        "extract_content_marker_ocr",
        "extract_content_mistral_ocr",
        "extract_content_nanonets_ocr",
        "extract_content_deepseek_ocr",
        "extract_barcode_data",
        "extract_barcode_raw_data",
        "extract_barcode_2ddoc_data",
        "llm_classify_document",
        "llm_extract_data",
        "save_workflow_result",
    ]
    workflow = _build_workflow(steps)
    event_v1 = _build_event(version=1)
    workflow_context = _build_context()
    session = MagicMock(spec=AsyncSession)

    with patch(
        "document_ia_worker.workflow.step_factory_v1.DownloadFileStep",
        return_value="download",
    ) as mock_download, patch(
        "document_ia_worker.workflow.step_factory_v1.PreprocessFileStep",
        return_value="preprocess",
    ) as mock_preprocess, patch(
        "document_ia_worker.workflow.step_factory_v1.ExtractContentOcrStep",
        return_value="extract_ocr",
    ) as mock_extract_ocr, patch(
        "document_ia_worker.workflow.step_factory_v1.MarkerHttpHttpOcrService",
        return_value="marker_service",
    ), patch(
        "document_ia_worker.workflow.step_factory_v1.MistralHttpOcrService",
        return_value="mistral_service",
    ), patch(
        "document_ia_worker.workflow.step_factory_v1.NanonetsHttpHttpOcrService",
        return_value="nanonets_service",
    ), patch(
        "document_ia_worker.workflow.step_factory_v1.DeepSeekHttpHttpOcrService",
        return_value="deepseek_service",
    ), patch(
        "document_ia_worker.workflow.step_factory_v1.ExtractContentHttpOcrStep",
        side_effect=["marker_step", "mistral_step", "nanonets_step", "deepseek_step"],
    ) as mock_extract_http, patch(
        "document_ia_worker.workflow.step_factory_v1.ExtractBarcodeData",
        return_value="barcode",
    ) as mock_barcode, patch(
        "document_ia_worker.workflow.step_factory_v1.ExtractBarcodeRawData",
        return_value="barcode_raw",
    ) as mock_barcode_raw, patch(
        "document_ia_worker.workflow.step_factory_v1.ExtractBarcode2DDocData",
        return_value="barcode_2ddoc",
    ) as mock_barcode_2ddoc, patch(
        "document_ia_worker.workflow.step_factory_v1.LLMClassifyDocumentStep",
        return_value="llm_classify",
    ) as mock_llm_classify, patch(
        "document_ia_worker.workflow.step_factory_v1.LLMExtractDocumentStep",
        return_value="llm_extract",
    ) as mock_llm_extract, patch(
        "document_ia_worker.workflow.step_factory_v1.SaveWorkflowResultStep",
        return_value="save_result",
    ) as mock_save:
        result = prepareStepListsV1(
            steps=steps,
            workflow=workflow,
            event_v1=event_v1,
            workflow_context=workflow_context,
            session=session,
        )

    assert result == [
        "download",
        "preprocess",
        "extract_ocr",
        "marker_step",
        "mistral_step",
        "nanonets_step",
        "deepseek_step",
        "barcode",
        "barcode_raw",
        "barcode_2ddoc",
        "llm_classify",
        "llm_extract",
        "save_result",
    ]

    mock_download.assert_called_once_with(
        workflow_context,
        event_v1.s3_file_info,
        event_v1.file_url,
    )
    assert mock_extract_http.call_count == 4
    mock_barcode.assert_called_once_with()
    mock_barcode_raw.assert_called_once_with()
    mock_barcode_2ddoc.assert_called_once_with()
    assert workflow_context.classification_parameters is not None
    assert workflow_context.extraction_parameters is not None

    mock_llm_classify.assert_called_once_with(
        workflow_context,
        workflow_context.classification_parameters.llm_model,
    )
    mock_llm_extract.assert_called_once_with(
        workflow_context,
        workflow_context.extraction_parameters.llm_model,
    )
    mock_save.assert_called_once_with(workflow_context, workflow.id, session)


def test_prepare_step_lists_v1_falls_back_to_workflow_llm_model():
    steps = ["llm_classify_document", "llm_extract_data"]
    workflow = _build_workflow(steps)
    event_v1 = _build_event(version=1)
    workflow_context = MainWorkflowContext(
        execution_id="exec-1",
        start_time=datetime.now(UTC),
        organization_id=uuid4(),
        classification_parameters=None,
        extraction_parameters=None,
        steps_metadata=[],
    )

    with patch(
        "document_ia_worker.workflow.step_factory_v1.LLMClassifyDocumentStep",
        return_value="llm_classify",
    ) as mock_llm_classify, patch(
        "document_ia_worker.workflow.step_factory_v1.LLMExtractDocumentStep",
        return_value="llm_extract",
    ) as mock_llm_extract:
        result = prepareStepListsV1(
            steps=steps,
            workflow=workflow,
            event_v1=event_v1,
            workflow_context=workflow_context,
            session=MagicMock(spec=AsyncSession),
        )

    assert result == ["llm_classify", "llm_extract"]
    mock_llm_classify.assert_called_once_with(workflow_context, workflow.llm_model)
    mock_llm_extract.assert_called_once_with(workflow_context, workflow.llm_model)
