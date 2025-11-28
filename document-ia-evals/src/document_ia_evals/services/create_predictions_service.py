"""Prediction service for running workflows on Label Studio datasets."""

import base64
import io
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from label_studio_sdk import LabelStudio

from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.label_studio import dict_to_annotation_result
from document_ia_evals.utils.s3 import download_from_s3, get_content_type_from_filename


@dataclass
class TaskProcessingResult:
    """Result of processing a single task."""
    
    task_id: int
    success: bool
    error: str | None = None
    execution_id: str | None = None
    total_processing_time_ms: int = -1


def extract_s3_url_from_task_url(pdf_url: str) -> str:
    """
    Extract and decode the S3 URL from a Label Studio task URL.
    
    The URL may be:
    - A direct s3:// URL
    - A presigned URL with a base64-encoded fileuri parameter
    - A base64-encoded S3 URL
    
    Args:
        pdf_url: URL from Label Studio task data
    
    Returns:
        Decoded S3 URL
    
    Raises:
        ValueError: If URL cannot be parsed
    """
    # Case 1: Direct S3 URL
    if pdf_url.startswith('s3://'):
        return pdf_url
    
    # Case 2: Presigned URL with fileuri parameter
    if 'fileuri=' in pdf_url:
        parsed = urlparse(pdf_url)
        query_params = parse_qs(parsed.query)
        fileuri_encoded = query_params.get('fileuri', [None])[0]
        
        if fileuri_encoded:
            # Add padding if needed for base64
            missing_padding = len(fileuri_encoded) % 4
            if missing_padding:
                fileuri_encoded += '=' * (4 - missing_padding)
            return base64.b64decode(fileuri_encoded).decode('utf-8')
    
    # Case 3: Try to decode as base64
    try:
        missing_padding = len(pdf_url) % 4
        if missing_padding:
            pdf_url += '=' * (4 - missing_padding)
        decoded = base64.b64decode(pdf_url).decode('utf-8')
        if decoded.startswith('s3://'):
            return decoded
    except Exception:
        pass
    
    # Return as-is if no decoding worked
    return pdf_url


def process_single_task(
    task: Any,
    workflow_id: str,
    api_key: str,
    ls_client: LabelStudio,
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
) -> TaskProcessingResult:
    """
    Process a single task: download file, execute workflow, create prediction.
    
    Args:
        task: Label Studio task object
        workflow_id: ID of the workflow to execute
        api_key: API key for Document IA API
        ls_client: Label Studio client
        model_version: Optional model version for the prediction
        extraction_parameters: Optional extraction parameters
    
    Returns:
        TaskProcessingResult with success status and details
    """
    task_id = task.id
    execution_id: str | None = None
    
    try:
        # Get URL from task data
        pdf_url = task.data.get('pdf') if task.data else None
        if not pdf_url:
            return TaskProcessingResult(
                task_id=task_id,
                success=False,
                error="No PDF URL found in task data"
            )
        
        # Extract S3 URL
        try:
            s3_url = extract_s3_url_from_task_url(pdf_url)
        except Exception as e:
            return TaskProcessingResult(
                task_id=task_id,
                success=False,
                error=f"Failed to extract S3 URL: {e}"
            )
        
        # Download file from S3
        try:
            file_content, filename = download_from_s3(s3_url)
        except Exception as e:
            return TaskProcessingResult(
                task_id=task_id,
                success=False,
                error=f"Failed to download file from {s3_url}: {e}"
            )
        
        # Determine content type from filename
        content_type = get_content_type_from_filename(filename)
        
        # Create file-like object for API
        file_obj = io.BytesIO(file_content)
        file_obj.name = filename
        file_obj.type = content_type  # type: ignore
        
        # Execute workflow
        workflow_execute_response = execute_workflow(
            workflow_id,
            file_obj,
            api_key,
            extraction_parameters=extraction_parameters,
        )
        
        execution_id = workflow_execute_response.data.execution_id
        if not execution_id:
            return TaskProcessingResult(
                task_id=task_id,
                success=False,
                error="Failed to get execution_id from workflow response"
            )
        
        execution_details = wait_for_execution(execution_id, api_key)
        
        # Check status
        if not execution_details or execution_details.status.upper() != "SUCCESS":
            status = execution_details.status if execution_details else 'unknown'
            return TaskProcessingResult(
                task_id=task_id,
                success=False,
                error=f"Workflow failed with status: {status} (execution_id: {execution_id})",
                execution_id=execution_id
            )
        
        # Extract the result from execution details
        workflow_data = execution_details.data
        result_data = workflow_data.result
        
        # Extract properties from extraction.properties array
        annotation_data: dict[str, Any] = {}
        if result_data.extraction is not None and result_data.extraction.properties:
            properties_array = result_data.extraction.properties
            for prop in properties_array:
                if prop.name and prop.value:
                    annotation_data[prop.name] = prop.value
        
        # Create prediction result
        prediction_result = dict_to_annotation_result(
            annotation_data,
            metadata={"total_processing_time_ms": execution_details.data.total_processing_time_ms}
        )
        
        # Create prediction in Label Studio
        ls_client.predictions.create(  # type: ignore
            task=task_id,
            result=prediction_result,
            model_version=model_version or workflow_id
        )
        
        return TaskProcessingResult(
            task_id=task_id,
            success=True,
            execution_id=execution_id,
            total_processing_time_ms=execution_details.data.total_processing_time_ms
        )
        
    except Exception as e:
        return TaskProcessingResult(
            task_id=task_id,
            success=False,
            error=str(e),
            execution_id=execution_id
        )


def _task_consumer(
    task_queue: queue.Queue[Any],
    workflow_id: str,
    api_key: str,
    ls_client: LabelStudio,
    callback: queue.Queue[TaskProcessingResult],
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
) -> None:
    """
    Consumer function for processing tasks from a queue.
    
    This runs in a separate thread and processes tasks until the queue is empty.
    """
    while True:
        try:
            task = task_queue.get(block=False)
        except queue.Empty:
            return
        
        result = process_single_task(
            task=task,
            workflow_id=workflow_id,
            api_key=api_key,
            ls_client=ls_client,
            model_version=model_version,
            extraction_parameters=extraction_parameters,
        )
        callback.put(result)


def run_workflow_on_dataset(
    workflow_id: str,
    project_id: int,
    api_key: str,
    ls_client: LabelStudio,
    n_workers: int = 5,
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[int, dict[str, Any]]:
    """
    Run workflow on all tasks in a Label Studio project.
    
    Args:
        workflow_id: ID of the workflow to execute
        project_id: Label Studio project ID
        api_key: API key for Document IA API
        ls_client: Label Studio client
        n_workers: Number of parallel workers
        model_version: Optional model version for predictions
        extraction_parameters: Optional extraction parameters
        on_progress: Optional callback for progress updates (current, total)
    
    Returns:
        Dictionary mapping task IDs to their processing results
    """
    # Get all tasks from the project
    tasks = [task for task in ls_client.tasks.list(project=project_id, fields='all')]
    
    if not tasks:
        return {}
    
    results: dict[int, dict[str, Any]] = {}
    
    threads: list[threading.Thread] = []
    task_queue: queue.Queue[Any] = queue.Queue()
    callback: queue.Queue[TaskProcessingResult] = queue.Queue()
    
    # Fill task queue
    for task in tasks:
        task_queue.put(task)
    
    # Start worker threads
    for _ in range(min(n_workers, len(tasks))):
        t = threading.Thread(
            target=_task_consumer,
            args=(
                task_queue,
                workflow_id,
                api_key,
                ls_client,
                callback,
                model_version,
                extraction_parameters,
            ),
            daemon=True
        )
        t.start()
        threads.append(t)
    
    # Collect results
    for i in range(len(tasks)):
        result = callback.get()
        results[result.task_id] = {
            'success': result.success,
            'error': result.error,
            'execution_id': result.execution_id,
            'total_processing_time_ms': result.total_processing_time_ms
        }
        if on_progress:
            on_progress(i + 1, len(tasks))
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    return results


def get_task_count(ls_client: LabelStudio, project_id: int) -> int:
    """
    Get the number of tasks in a Label Studio project.
    
    Args:
        ls_client: Label Studio client
        project_id: Label Studio project ID
    
    Returns:
        Number of tasks in the project
    """
    tasks = [task for task in ls_client.tasks.list(project=project_id, fields='all')]
    return len(tasks)


def get_processing_statistics(
    results: dict[int, dict[str, Any]]
) -> tuple[int, int]:
    """
    Get statistics from processing results.
    
    Args:
        results: Dictionary of task processing results
    
    Returns:
        Tuple of (success_count, total_count)
    """
    success_count = sum(1 for r in results.values() if r['success'])
    return success_count, len(results)


def get_failed_tasks(
    results: dict[int, dict[str, Any]]
) -> list[tuple[int, str | None, str | None, int]]:
    """
    Get list of failed tasks with their error messages.
    
    Args:
        results: Dictionary of task processing results
    
    Returns:
        List of tuples (task_id, error_message, execution_id, processing_time_ms)
    """
    return [
        (
            task_id,
            result.get('error'),
            result.get('execution_id'),
            result.get('total_processing_time_ms', -1)
        )
        for task_id, result in results.items()
        if not result['success']
    ]

