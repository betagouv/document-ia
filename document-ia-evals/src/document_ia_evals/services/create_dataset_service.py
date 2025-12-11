"""Dataset creation service for processing documents and uploading to S3."""

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

from streamlit.runtime.uploaded_file_manager import UploadedFile

from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import create_task
from document_ia_evals.utils.s3 import (
    build_s3_url,
    get_file_extension,
    get_s3_client,
    upload_to_s3_with_task,
)
from document_ia_schemas import SupportedDocumentType


@dataclass
class FileProcessingResult:
    """Result of processing a single file."""
    
    file_name: str
    success: bool
    error: str | None = None
    execution_id: str | None = None


def process_single_file(
    uploaded_file: UploadedFile,
    api_key: str,
    workflow_id: str,
    s3_prefix: str,
    bucket_name: str,
    document_type: SupportedDocumentType | None = None,
    is_fast_workflow: bool = False,
) -> FileProcessingResult:
    """
    Process a single file: execute workflow, upload to S3 with ground truth.
    
    Args:
        uploaded_file: The file to process
        api_key: API key for Document IA API
        workflow_id: ID of the workflow to execute
        s3_prefix: S3 prefix path for the dataset
        bucket_name: S3 bucket name
        document_type: Optional document type for fast workflows
        is_fast_workflow: Whether the workflow is a fast workflow
    
    Returns:
        FileProcessingResult with success status and any error details
    """
    file_id = uploaded_file.name.rsplit('.', 1)[0]  # Remove extension
    execution_id: str | None = None
    
    try:
        # Prepare extraction parameters for fast workflows
        extraction_parameters = None
        if is_fast_workflow and document_type:
            extraction_parameters = {"document-type": document_type.value}
        
        # Execute workflow to get ground truth
        workflow_execute_response = execute_workflow(
            workflow_id,
            uploaded_file,
            api_key,
            extraction_parameters=extraction_parameters,
        )
        
        execution_id = workflow_execute_response.data.execution_id
        if not execution_id:
            return FileProcessingResult(
                file_name=uploaded_file.name,
                success=False,
                error="Failed to get execution_id from workflow response",
                execution_id=None
            )
        
        execution_details = wait_for_execution(execution_id, api_key)
        
        # Check status
        if not execution_details or execution_details.status != ExecutionStatus.SUCCESS:
            return FileProcessingResult(
                file_name=uploaded_file.name,
                success=False,
                error=f"Workflow failed with status: {execution_details} (execution_id: {execution_id})",
                execution_id=execution_id
            )
        
        # Extract the result from the execution details data
        workflow_data = execution_details.data
        extracted_fields = workflow_data.result.extraction
        
        if extracted_fields is None:
            return FileProcessingResult(
                file_name=uploaded_file.name,
                success=False,
                error="Failed to get extracted_fields",
                execution_id=execution_id
            )
        
        # Convert list format [{name, value, type}] to dict {name: value}
        properties = extracted_fields.properties
        result_data: dict[str, Any] = {
            item.name: item.value
            for item in properties
            if item.name and item.value
        }
        
        # Read file content
        uploaded_file.seek(0)
        file_content = uploaded_file.read()
        
        # Determine content type
        content_type = uploaded_file.type or 'application/octet-stream'
        
        # Build S3 URL for the raw file
        ext = get_file_extension(content_type)
        raw_key = f"{s3_prefix}/source/{file_id}{ext}"
        pdf_url = build_s3_url(bucket_name, raw_key)
        
        # Create Label Studio task
        task_data = create_task(pdf_url=pdf_url, ground_truth=result_data)
        
        # Get S3 client and upload
        s3_client = get_s3_client()
        upload_to_s3_with_task(
            s3_client=s3_client,
            bucket=bucket_name,
            prefix=s3_prefix,
            file_id=file_id,
            file_content=file_content,
            content_type=content_type,
            task_data=task_data
        )
        
        return FileProcessingResult(
            file_name=uploaded_file.name,
            success=True,
            execution_id=execution_id
        )
        
    except Exception as e:
        return FileProcessingResult(
            file_name=uploaded_file.name,
            success=False,
            error=str(e),
            execution_id=execution_id
        )


def _file_consumer(
    file_queue: queue.Queue[UploadedFile],
    api_key: str,
    callback: queue.Queue[FileProcessingResult],
    workflow_id: str,
    s3_prefix: str,
    bucket_name: str,
    document_type: SupportedDocumentType | None = None,
    is_fast_workflow: bool = False,
) -> None:
    """
    Consumer function for processing files from a queue.
    
    This runs in a separate thread and processes files until the queue is empty.
    """
    while True:
        try:
            uploaded_file: UploadedFile = file_queue.get(block=False)
        except queue.Empty:
            return
        
        result = process_single_file(
            uploaded_file=uploaded_file,
            api_key=api_key,
            workflow_id=workflow_id,
            s3_prefix=s3_prefix,
            bucket_name=bucket_name,
            document_type=document_type,
            is_fast_workflow=is_fast_workflow,
        )
        callback.put(result)


def process_files_parallel(
    files: list[UploadedFile],
    api_key: str,
    workflow_id: str,
    s3_prefix: str,
    n_workers: int = 5,
    document_type: SupportedDocumentType | None = None,
    is_fast_workflow: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Process files in parallel and upload to S3 with ground truth annotations.
    
    Args:
        files: List of uploaded files to process
        api_key: API key for Document IA API
        workflow_id: ID of the workflow to execute
        s3_prefix: S3 prefix path for the dataset
        n_workers: Number of parallel workers
        document_type: Optional document type for fast workflows
        is_fast_workflow: Whether the workflow is a fast workflow
        on_progress: Optional callback for progress updates (current, total)
    
    Returns:
        Dictionary mapping file names to their processing results
    """
    bucket_name = config.S3_BUCKET_NAME or ''
    results: dict[str, dict[str, Any]] = {}
    
    threads: list[threading.Thread] = []
    file_queue: queue.Queue[UploadedFile] = queue.Queue()
    callback: queue.Queue[FileProcessingResult] = queue.Queue()
    
    # Add all files to the queue
    for file in files:
        file_queue.put(file)
    
    # Start worker threads
    for _ in range(min(n_workers, len(files))):
        t = threading.Thread(
            target=_file_consumer,
            args=(
                file_queue,
                api_key,
                callback,
                workflow_id,
                s3_prefix,
                bucket_name,
                document_type,
                is_fast_workflow,
            ),
            daemon=True
        )
        t.start()
        threads.append(t)
    
    # Collect results
    for i in range(len(files)):
        result = callback.get()
        results[result.file_name] = {
            'success': result.success,
            'error': result.error,
            'execution_id': result.execution_id
        }
        if on_progress:
            on_progress(i + 1, len(files))
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    return results


def get_upload_statistics(results: dict[str, dict[str, Any]]) -> tuple[int, int]:
    """
    Get statistics from upload results.
    
    Args:
        results: Dictionary of file processing results
    
    Returns:
        Tuple of (success_count, total_count)
    """
    success_count = sum(1 for r in results.values() if r['success'])
    return success_count, len(results)


def get_failed_uploads(
    results: dict[str, dict[str, Any]]
) -> list[tuple[str, str | None, str | None]]:
    """
    Get list of failed uploads with their error messages.
    
    Args:
        results: Dictionary of file processing results
    
    Returns:
        List of tuples (file_name, error_message, execution_id)
    """
    return [
        (name, result.get('error'), result.get('execution_id'))
        for name, result in results.items()
        if not result['success']
    ]

