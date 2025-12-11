"""Metric evaluation service for running experiments on Label Studio datasets."""

import json
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from label_studio_sdk import Client

from document_ia_evals.metrics import metric_registry
from document_ia_evals.utils.label_studio import annotation_results_to_dict


@dataclass
class EvaluationProgress:
    """Progress information for evaluation."""
    current: int
    total: int
    current_task_id: int | str = "Unknown"


@dataclass 
class EvaluationObservation:
    """Single observation from metric evaluation."""
    task_id: int | str
    model_version: str
    prediction_id: int | str
    score: float
    observation: str
    output: Any
    processing_time_ms: int | None = None
    error: str | None = None


@dataclass
class EvaluationResults:
    """Complete results from metric evaluation."""
    project_id: int
    project_title: str
    metric_name: str
    observations: list[dict[str, Any]]
    total_tasks: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    error: str | None = None


def get_metric_info(metric_name: str) -> dict[str, Any]:
    """
    Get metric information from registry.
    
    Args:
        metric_name: Name of the metric
    
    Returns:
        Metric information dictionary
    
    Raises:
        ValueError: If metric not found
    """
    metric_info = metric_registry.get_metric(metric_name)
    if not metric_info:
        raise ValueError(f"Metric '{metric_name}' not found in registry")
    return metric_info


def prepare_metric_inputs(
    metric_info: dict[str, Any],
    pred_data: dict[str, Any],
    ground_truth: dict[str, Any],
    task_data: dict[str, Any],
    document_type: str | None = None,
) -> dict[str, Any]:
    """
    Prepare inputs for metric function based on required fields.
    
    Args:
        metric_info: Metric information from registry
        pred_data: Prediction data
        ground_truth: Ground truth data
        task_data: Task data from Label Studio
        document_type: Optional document type override
    
    Returns:
        Dictionary of metric inputs
    """
    required_fields = metric_info.get('require', [])
    metric_inputs: dict[str, Any] = {}
    
    # Map common field names
    if 'prediction' in required_fields:
        metric_inputs['prediction'] = pred_data
    if 'ground_truth' in required_fields:
        metric_inputs['ground_truth'] = ground_truth
    if 'output' in required_fields:
        metric_inputs['output'] = pred_data
    if 'output_true' in required_fields:
        metric_inputs['output_true'] = ground_truth
    if 'query' in required_fields:
        metric_inputs['query'] = task_data
    
    # Handle document_type parameter
    if 'document_type' in required_fields:
        resolved_doc_type = document_type
        
        # If not provided, try to infer from data
        if not resolved_doc_type:
            if isinstance(pred_data, dict) and 'type' in pred_data:
                resolved_doc_type = pred_data['type']
            elif isinstance(ground_truth, dict) and 'type' in ground_truth:
                resolved_doc_type = ground_truth['type']
            elif 'document_type' in task_data:
                resolved_doc_type = task_data['document_type']
        
        if resolved_doc_type:
            metric_inputs['document_type'] = resolved_doc_type
    
    return metric_inputs


def run_metric_evaluation(
    project_id: int,
    metric_name: str,
    client: Client,
    document_type: str | None = None,
    on_progress: Callable[[EvaluationProgress], None] | None = None,
) -> EvaluationResults:
    """
    Run metric evaluation on all tasks in a Label Studio project.
    
    Args:
        project_id: Label Studio project ID
        metric_name: Name of the metric to apply
        client: Label Studio client
        document_type: Optional document type for metrics that require it
        on_progress: Optional callback for progress updates
    
    Returns:
        EvaluationResults with experiment data
    """
    # Get the metric
    metric_info = get_metric_info(metric_name)
    metric_func = metric_info['func']
    required_fields = metric_info.get('require', [])
    
    # Get the project
    try:
        project = client.get_project(project_id)
        project_params = project.get_params()
    except Exception as e:
        raise ValueError(f"Failed to get project {project_id}: {str(e)}")
    
    # Fetch tasks
    tasks = project.get_tasks()
    
    if not tasks:
        return EvaluationResults(
            project_id=project_id,
            project_title=project_params.get('title', 'Unknown'),
            metric_name=metric_name,
            observations=[],
            error="No tasks found in project"
        )
    
    # Process tasks
    observations: list[dict[str, Any]] = []
    processed_count = 0
    skipped_count = 0
    
    for idx, task in enumerate(tasks):
        task_id = task.get('id', 'Unknown')
        
        # Report progress
        if on_progress:
            on_progress(EvaluationProgress(
                current=idx + 1,
                total=len(tasks),
                current_task_id=task_id
            ))
        
        # Extract ground truth
        ground_truth = None
        for annotation in task.get('annotations', []):
            if annotation.get('ground_truth'):
                ground_truth, _ = annotation_results_to_dict(annotation.get('result', []))
                break
        
        # Skip if no ground truth
        if ground_truth is None:
            skipped_count += 1
            continue
        
        # Process predictions
        predictions = task.get('predictions', [])
        if not predictions:
            skipped_count += 1
            continue
        
        for prediction in predictions:
            model_version = prediction.get('model_version', 'Unknown')
            pred_data, pred_data_meta = annotation_results_to_dict(prediction.get('result', []))
            
            # Extract processing time from metadata
            processing_time_ms = None
            if pred_data_meta and isinstance(pred_data_meta, dict):
                processing_time_ms = pred_data_meta.get('total_processing_time_ms')
            
            if pred_data is None:
                skipped_count += 1
                continue
            
            # Run the metric
            try:
                # Prepare metric inputs
                metric_inputs = prepare_metric_inputs(
                    metric_info=metric_info,
                    pred_data=pred_data,
                    ground_truth=ground_truth,
                    task_data=task.get('data', {}),
                    document_type=document_type,
                )
                
                # Check if document_type is required but missing
                if 'document_type' in required_fields and 'document_type' not in metric_inputs:
                    observations.append({
                        "task_id": task_id,
                        "model_version": model_version,
                        "prediction_id": prediction.get('id', 'Unknown'),
                        "score": 0.0,
                        "observation": json.dumps({"error": f"Could not infer document_type for task {task_id}"}),
                        "output": None,
                        "processing_time_ms": processing_time_ms
                    })
                    skipped_count += 1
                    continue
                
                # Run metric
                score, observation_json, output = metric_func(**metric_inputs)
                
                observations.append({
                    "task_id": task_id,
                    "model_version": model_version,
                    "prediction_id": prediction.get('id', 'Unknown'),
                    "score": score,
                    "observation": observation_json,
                    "output": output,
                    "processing_time_ms": processing_time_ms
                })
                
                processed_count += 1
            
            except Exception as e:
                observations.append({
                    "task_id": task_id,
                    "model_version": model_version,
                    "prediction_id": prediction.get('id', 'Unknown'),
                    "score": 0.0,
                    "observation": json.dumps({"error": str(e)}),
                    "output": None,
                    "processing_time_ms": processing_time_ms
                })
                skipped_count += 1
    
    return EvaluationResults(
        project_id=project_id,
        project_title=project_params.get('title', 'Unknown'),
        metric_name=metric_name,
        observations=observations,
        total_tasks=len(tasks),
        processed_count=processed_count,
        skipped_count=skipped_count
    )


def calculate_processing_time_stats(
    observations: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """
    Calculate processing time statistics grouped by model version.
    
    Args:
        observations: List of observation dictionaries
    
    Returns:
        Dictionary mapping model_version to statistics
    """
    # Group processing times by model version
    processing_times_by_model: dict[str, list[float]] = {}
    
    for obs in observations:
        model_version = obs.get('model_version', 'Unknown')
        processing_time = obs.get('processing_time_ms')
        
        if processing_time is not None:
            if model_version not in processing_times_by_model:
                processing_times_by_model[model_version] = []
            processing_times_by_model[model_version].append(processing_time)
    
    # Calculate statistics
    stats: dict[str, dict[str, Any]] = {}
    
    for model_version, times in sorted(processing_times_by_model.items()):
        if times:
            stats[model_version] = {
                "mean_ms": float(np.mean(times)),
                "median_ms": float(np.median(times)),
                "std_dev_ms": float(np.std(times)),
                "min_ms": float(min(times)),
                "max_ms": float(max(times)),
                "sample_count": len(times)
            }
    
    return stats


def results_to_dict(results: EvaluationResults) -> dict[str, Any]:
    """
    Convert EvaluationResults to dictionary format.
    
    Args:
        results: EvaluationResults dataclass
    
    Returns:
        Dictionary representation
    """
    return {
        "project_id": results.project_id,
        "project_title": results.project_title,
        "metric_name": results.metric_name,
        "observations": results.observations,
        "total_tasks": results.total_tasks,
        "processed_count": results.processed_count,
        "skipped_count": results.skipped_count,
        "error": results.error
    }

