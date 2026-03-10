import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from document_ia_api.api.contracts.execution.response import ExecutionResponse
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_api.api.contracts.workflow import (
    WorkflowClassificationParameterRequest,
    WorkflowExtractionParameterRequest,
)
from document_ia_api.api.exceptions.entity_not_found_exception import (
    HttpEntityNotFoundException,
)
from document_ia_api.application.services.execution_service import ExecutionService
from document_ia_api.core.config import workflow_settings
from document_ia_api.core.file_validator import validate_uploaded_file
from document_ia_api.infra.s3_service import s3_service
from document_ia_api.schemas.workflow import WorkflowExecutionData
from document_ia_infra.core.model.file_info import FileInfo
from document_ia_infra.data.event.schema.workflow.workflow_execution_started_event import (
    ClassificationParameters,
    ExtractionParameters,
)
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_infra.redis.model.workflow_execution_message import (
    WorkflowExecutionMessage,
)
from document_ia_infra.redis.publisher import Publisher
from document_ia_infra.redis.redis_settings import redis_settings
from document_ia_infra.service.event_store_service import EventStoreService
from document_ia_infra.exception.entity_not_found_exception import (
    EntityNotFoundException,
)

logger = logging.getLogger(__name__)


class WorkflowService:
    """Service for handling workflow execution business logic."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.redis_producer = Publisher[WorkflowExecutionMessage](
            redis_settings.EVENT_STREAM_NAME
        )

    async def execute_workflow(
        self,
        organization_id: uuid.UUID,
        workflow_id: str,
        file: Optional[UploadFile],
        file_url: Optional[str],
        metadata_json: Optional[str],
        request_classification_parameter: Optional[
            WorkflowClassificationParameterRequest
        ],
        request_extraction_parameter: Optional[WorkflowExtractionParameterRequest],
    ) -> WorkflowExecutionData:
        """
        Execute a workflow with file upload and metadata processing.

        Args:
            workflow_id: Unique identifier for the workflow
            organization_id: Organization UUID
            file: Uploaded file
            file_url: URL of the file to be processed
            metadata_json: JSON string containing metadata
            request_classification_parameter: Workflow classification parameter
            request_extraction_parameter: Workflow extraction parameter

        Returns:
            Dict containing execution response

        Raises:
            HTTPException: If execution fails
        """
        try:
            workflow = await workflow_repository.get_workflow_by_id(workflow_id)

            # Validate workflow ID
            if not workflow:
                raise HttpEntityNotFoundException(
                    entity_name="workflow", entity_id=workflow_id
                )

            # Validate and parse metadata
            metadata = self._parse_metadata(metadata_json)

            # Generate execution ID
            execution_id = str(uuid.uuid4())

            file_info: Optional[FileInfo] = None

            if file is not None:
                # Validate uploaded file
                detected_mime_type = validate_uploaded_file(file)

                # Read file content
                file_content = await self._read_file_content(file)

                # Upload file to S3
                s3_upload_result = await self._upload_file_to_s3(
                    file_content, file.filename, detected_mime_type, metadata
                )

                # Prepare file info

                file_info = FileInfo(
                    filename=file.filename or "unknown",
                    s3_key=s3_upload_result["s3_key"],
                    size=len(file_content),
                    content_type=detected_mime_type,
                    uploaded_at=datetime.now().isoformat(),
                    presigned_url=s3_upload_result["presigned_url"],
                )

                logger.info(
                    f"Workflow execution started: {execution_id} "
                    f"(workflow: {workflow_id}, file: {file.filename})"
                )

            else:
                logger.info(
                    f"Workflow execution started: {execution_id} "
                    f"(workflow: {workflow_id}, file_url: {file_url})"
                )

            # Emit workflow started event
            try:
                event_store_service = EventStoreService(self.db_session)

                await event_store_service.emit_workflow_started(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    organization_id=organization_id,
                    file_info=file_info,
                    file_url=file_url,
                    metadata=metadata,
                    classification_parameters=self._map_classification_parameters(
                        request_classification_parameter
                    ),
                    extraction_parameters=self._map_extraction_parameters(
                        request_extraction_parameter
                    ),
                )
                logger.debug(
                    f"Workflow started event emitted for execution {execution_id}"
                )

            except Exception as e:
                logger.error(f"Failed to emit workflow started event: {e}")
                # Don't fail the workflow execution if event emission fails

            publish_id = await self.redis_producer.publish_message(
                WorkflowExecutionMessage(workflow_execution_id=execution_id)
            )
            if not publish_id:
                logger.warning(
                    f"Workflow execution {execution_id}: message not published to Redis stream {self.redis_producer.stream_name}"
                )

            return WorkflowExecutionData(
                execution_id=execution_id,
                workflow_id=workflow_id,
                status="processing",
                created_at=datetime.now().isoformat(),
                file_info=file_info,
                file_url=file_url,
                metadata=metadata,
            )

        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "internal_error",
                    "message": "An internal server error occurred during workflow execution",
                },
            )

    async def wait_for_execution_result(
        self,
        execution_id: str,
        organization_id: uuid.UUID,
        *,
        is_debug_mode: bool = False,
        timeout_seconds: Optional[int] = None,
        poll_interval_ms: Optional[int] = None,
    ) -> ExecutionResponse:
        """Poll the event store until the execution completes or timeout elapses."""

        event_store_service = EventStoreService(self.db_session)
        execution_service = ExecutionService()

        configured_timeout = workflow_settings.SYNC_EXECUTION_TIMEOUT_SECONDS
        configured_max_wait = workflow_settings.SYNC_EXECUTION_MAX_WAIT_SECONDS
        effective_timeout = min(
            timeout_seconds or configured_timeout,
            configured_max_wait,
        )
        poll_interval = max(
            0.05,
            (poll_interval_ms or workflow_settings.SYNC_EXECUTION_POLL_INTERVAL_MS)
            / 1000,
        )

        deadline = time.monotonic() + effective_timeout
        last_model: Optional[ExecutionResponse] = None

        while time.monotonic() < deadline:
            try:
                event_dto = await event_store_service.get_last_event_for_execution_id(
                    execution_id
                )
            except EntityNotFoundException:
                # Event may not be visible yet, keep waiting until timeout.
                await asyncio.sleep(poll_interval)
                continue

            if event_dto.organization_id != organization_id:
                raise HTTPException(
                    status_code=401, detail="Unauthorized access to execution"
                )

            last_model = execution_service.get_event_model(
                event_dto, execution_id, is_debug_mode
            )

            if last_model.status != ExecutionStatus.STARTED:
                return last_model

            await asyncio.sleep(poll_interval)

        raise HTTPException(
            status_code=408,
            detail={
                "error": "sync_execution_timeout",
                "message": "Workflow execution did not finish before timeout",
                "execution_id": execution_id,
                "last_status": getattr(last_model, "status", "UNKNOWN"),
            },
        )

    def _parse_metadata(self, metadata_json: Optional[str]) -> Dict[str, Any]:
        """
        Parse and validate metadata JSON string.

        Args:
            metadata_json: JSON string containing metadata

        Returns:
            Parsed metadata dictionary

        Raises:
            HTTPException: If metadata parsing fails
        """

        if not metadata_json:
            return {}

        try:
            metadata: dict[str, Any] = json.loads(metadata_json)

            if not metadata:
                raise ValueError("Metadata cannot be empty")

            return metadata

        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_metadata",
                    "message": f"Invalid JSON format in metadata: {str(e)}",
                },
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail={"error": "invalid_metadata", "message": str(e)}
            )

    async def _read_file_content(self, file: UploadFile) -> bytes:
        """
        Read file content as bytes.

        Args:
            file: UploadFile object

        Returns:
            File content as bytes
        """
        try:
            content = await file.read()
            return content
        except Exception as e:
            logger.error(f"Error reading file content: {e}")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_read_error",
                    "message": "Failed to read uploaded file",
                },
            )

    async def _upload_file_to_s3(
        self,
        file_content: bytes,
        filename: Optional[str],
        content_type: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Upload file to S3/MinIO storage.

        Args:
            file_content: File content as bytes
            filename: Original filename
            content_type: Detected MIME type
            metadata: Execution metadata

        Returns:
            S3 upload result dictionary
        """
        try:
            # Prepare S3 metadata
            s3_metadata = {
                "workflow_metadata": json.dumps(metadata),
                "upload_source": "workflow_execution",
            }

            result = await s3_service.upload_file(
                file_data=file_content,
                filename=filename,
                content_type=content_type,
                metadata=s3_metadata,
            )

            logger.info(f"File uploaded to S3: {result['s3_key']}")
            return result

        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "s3_upload_error",
                    "message": "Failed to upload file to storage",
                },
            )

    def _map_classification_parameters(
        self,
        request_classification_parameter: Optional[
            WorkflowClassificationParameterRequest
        ],
    ) -> Optional[ClassificationParameters]:
        if request_classification_parameter is None:
            return None
        parameters: ClassificationParameters = ClassificationParameters()
        if request_classification_parameter.llm_model:
            parameters.llm_model = request_classification_parameter.llm_model
        return parameters

    def _map_extraction_parameters(
        self, request_extraction_parameter: Optional[WorkflowExtractionParameterRequest]
    ) -> Optional[ExtractionParameters]:
        if request_extraction_parameter is None:
            return None

        parameters: ExtractionParameters = ExtractionParameters()
        parameters.llm_model = request_extraction_parameter.llm_model
        parameters.document_type = request_extraction_parameter.document_type
        return parameters
