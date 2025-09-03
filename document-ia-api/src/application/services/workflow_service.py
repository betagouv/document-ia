import logging
import uuid
import json
from datetime import datetime
from typing import Dict, Any
from fastapi import HTTPException, UploadFile

from core.file_validator import validate_uploaded_file
from infra.s3_service import s3_service
from infra.database.repositories.workflow import workflow_repository

from schemas.workflow import WorkflowExecutionData
from application.services.event_store_service import EventStoreService

logger = logging.getLogger(__name__)


class WorkflowService:
    """Service for handling workflow execution business logic."""

    async def execute_workflow(
        self, workflow_id: str, file: UploadFile, metadata_json: str
    ) -> Dict[str, Any]:
        """
        Execute a workflow with file upload and metadata processing.

        Args:
            workflow_id: Unique identifier for the workflow
            file: Uploaded file
            metadata_json: JSON string containing metadata

        Returns:
            Dict containing execution response

        Raises:
            HTTPException: If execution fails
        """
        try:
            workflow = await workflow_repository.get_workflow_by_id(workflow_id)

            # Validate workflow ID
            if not workflow:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error": "workflow_not_found",
                        "message": f"Workflow with ID '{workflow_id}' not found or disabled",
                    },
                )

            # Validate and parse metadata
            metadata = self._parse_metadata(metadata_json)

            # Validate uploaded file
            detected_mime_type = validate_uploaded_file(file)

            # Read file content
            file_content = await self._read_file_content(file)

            # Upload file to S3
            s3_upload_result = await self._upload_file_to_s3(
                file_content, file.filename, detected_mime_type, metadata
            )

            # Generate execution ID
            execution_id = str(uuid.uuid4())

            # Prepare file info
            file_info = {
                "filename": file.filename,
                "size": len(file_content),
                "content_type": detected_mime_type,
                "file_id": s3_upload_result["file_id"],
                "uploaded_at": datetime.now().isoformat(),
                "presigned_url": s3_upload_result["presigned_url"],
            }

            # Log successful execution
            logger.info(
                f"Workflow execution started: {execution_id} "
                f"(workflow: {workflow_id}, file: {file.filename})"
            )

            # Emit workflow started event
            try:
                # TODO: import session from database ? What for ?
                event_store_service = EventStoreService()
                await event_store_service.emit_workflow_started(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    file_info=file_info,
                    metadata=metadata,
                )
                logger.debug(
                    f"Workflow started event emitted for execution {execution_id}"
                )
            except Exception as e:
                logger.error(f"Failed to emit workflow started event: {e}")
                # Don't fail the workflow execution if event emission fails

            # TODO: Queue workflow processing job
            # await self._queue_workflow_processing(
            #     execution_id, workflow_id, s3_upload_result["s3_key"], metadata
            # )

            return WorkflowExecutionData(
                execution_id=execution_id,
                workflow_id=workflow_id,
                status="processing",
                created_at=datetime.now().isoformat(),
                file_info=file_info,
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

    def _parse_metadata(self, metadata_json: str) -> Dict[str, Any]:
        """
        Parse and validate metadata JSON string.

        Args:
            metadata_json: JSON string containing metadata

        Returns:
            Parsed metadata dictionary

        Raises:
            HTTPException: If metadata parsing fails
        """
        try:
            metadata = json.loads(metadata_json)

            # Validate metadata structure
            if not isinstance(metadata, dict):
                raise ValueError("Metadata must be a JSON object")

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
        filename: str,
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


# Global workflow service instance
workflow_service = WorkflowService()
