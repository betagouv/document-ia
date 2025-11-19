"""Experiment service for saving and loading experiment results."""

import json
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from document_ia_evals.database.models import Experiment, Observation
from document_ia_evals.database.connection import get_session


def save_experiment(
    project_id: int,
    metric_name: str,
    observations_data: List[Dict[str, Any]],
    total_tasks: int = 0,
    notes: Optional[str] = None
) -> UUID:
    """
    Save experiment results to database (PRIVACY-SAFE).
    
    Only stores:
    - References to Label Studio (IDs only)
    - Metric computation results (scores, field_scores)
    - NO raw data, predictions, or ground truth
    
    Args:
        project_id: Label Studio project ID
        metric_name: Name of the metric used
        observations_data: List of observation dictionaries with:
            - task_id: int
            - prediction_id: int
            - model_version: str
            - score: float
            - observation: str (JSON with field_scores, error)
        total_tasks: Total number of tasks processed
        notes: Optional notes about this experiment
    
    Returns:
        UUID: The ID of the created experiment
    """
    with get_session() as session:
        # Calculate statistics
        scores = [obs.get('score', 0.0) for obs in observations_data if obs.get('score') is not None]
        average_score = sum(scores) / len(scores) if scores else None
        
        # Count unique tasks that were processed (not total observations)
        # Multiple model_versions can create multiple observations per task
        unique_task_ids = set(obs.get('task_id') for obs in observations_data if obs.get('task_id') is not None)
        processed_count = len(unique_task_ids)
        
        # Use provided total_tasks, or fall back to unique task count
        actual_total_tasks = total_tasks if total_tasks > 0 else len(unique_task_ids)
        
        # Create experiment
        experiment = Experiment(
            label_studio_project_id=project_id,
            metric_name=metric_name,
            total_tasks=actual_total_tasks,
            processed_count=processed_count,
            average_score=average_score,
            status='completed',
            notes=notes
        )
        
        session.add(experiment)
        session.flush()  # Get the experiment ID
        
        # Create observations (PRIVACY-SAFE: only scores and IDs)
        for obs_data in observations_data:
            # Parse observation JSON to extract only what we need
            observation_json = obs_data.get('observation', '{}')
            try:
                if isinstance(observation_json, str):
                    parsed_obs = json.loads(observation_json)
                else:
                    parsed_obs = observation_json
            except json.JSONDecodeError:
                parsed_obs = {}
            
            # Extract ONLY privacy-safe data (scores, no raw data)
            metric_results = {
                'score': obs_data.get('score', 0.0),
                'field_scores': parsed_obs.get('field_scores', {}),
            }
            
            # Include error if present
            if 'error' in parsed_obs:
                metric_results['error'] = parsed_obs['error']
            
            observation = Observation(
                experiment_id=experiment.id,
                task_id=obs_data.get('task_id', 0),
                prediction_id=obs_data.get('prediction_id', 0),
                model_version=obs_data.get('model_version', 'Unknown'),
                score=obs_data.get('score', 0.0),
                metric_results=metric_results
            )
            
            session.add(observation)
        
        session.commit()
        return experiment.id


def load_experiment(experiment_id: UUID) -> Optional[Dict[str, Any]]:
    """
    Load an experiment from database.
    
    Returns data in the same format expected by render_results.
    
    Args:
        experiment_id: UUID of the experiment
    
    Returns:
        Dict with experiment data and observations, or None if not found
    """
    with get_session() as session:
        experiment = session.query(Experiment).filter_by(id=experiment_id).first()
        
        if not experiment:
            return None
        
        # Convert observations to format expected by render_results
        observations = []
        for obs in experiment.observations:
            # Reconstruct observation JSON for rendering
            observation_data = {
                'task_id': obs.task_id,
                'prediction_id': obs.prediction_id,
                'model_version': obs.model_version or 'Unknown',
                'score': obs.score,
                'observation': json.dumps(obs.metric_results) if obs.metric_results else '{}'
            }
            observations.append(observation_data)
        
        return {
            'experiment_id': str(experiment.id),
            'project_id': experiment.label_studio_project_id,
            'metric_name': experiment.metric_name,
            'created_at': experiment.created_at.isoformat(),
            'total_tasks': experiment.total_tasks,
            'processed_count': experiment.processed_count,
            'skipped_count': experiment.skipped_count,
            'average_score': experiment.average_score,
            'status': experiment.status,
            'notes': experiment.notes,
            'observations': observations
        }


def list_experiments(
    project_id: Optional[int] = None,
    metric_name: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    List experiments with optional filters.
    
    Args:
        project_id: Filter by Label Studio project ID
        metric_name: Filter by metric name
        limit: Maximum number of results
        offset: Number of results to skip
    
    Returns:
        List of experiment summaries
    """
    with get_session() as session:
        query = session.query(Experiment)
        
        # Apply filters
        if project_id is not None:
            query = query.filter(Experiment.label_studio_project_id == project_id)
        if metric_name:
            query = query.filter(Experiment.metric_name == metric_name)
        
        # Order by most recent first
        query = query.order_by(desc(Experiment.created_at))
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        experiments = query.all()
        
        return [
            {
                'id': str(exp.id),
                'project_id': exp.label_studio_project_id,
                'metric_name': exp.metric_name,
                'created_at': exp.created_at.isoformat(),
                'total_tasks': exp.total_tasks,
                'processed_count': exp.processed_count,
                'skipped_count': exp.skipped_count,
                'average_score': exp.average_score,
                'success_rate': exp.success_rate,
                'status': exp.status,
                'notes': exp.notes,
                'observation_count': len(exp.observations)
            }
            for exp in experiments
        ]


def delete_experiment(experiment_id: UUID) -> bool:
    """
    Delete an experiment and all its observations.
    
    Args:
        experiment_id: UUID of the experiment to delete
    
    Returns:
        bool: True if deleted, False if not found
    """
    with get_session() as session:
        experiment = session.query(Experiment).filter_by(id=experiment_id).first()
        
        if not experiment:
            return False
        
        session.delete(experiment)
        session.commit()
        return True


def get_experiment_statistics(
    project_id: Optional[int] = None,
    metric_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get aggregate statistics for experiments.
    
    Args:
        project_id: Filter by Label Studio project ID
        metric_name: Filter by metric name
    
    Returns:
        Dict with statistics
    """
    with get_session() as session:
        query = session.query(
            func.count(Experiment.id).label('total_experiments'),
            func.avg(Experiment.average_score).label('avg_score'),
            func.sum(Experiment.total_tasks).label('total_tasks'),
            func.sum(Experiment.processed_count).label('total_processed')
        )
        
        # Apply filters
        if project_id is not None:
            query = query.filter(Experiment.label_studio_project_id == project_id)
        if metric_name:
            query = query.filter(Experiment.metric_name == metric_name)
        
        result = query.first()
        
        return {
            'total_experiments': result.total_experiments or 0,
            'average_score': float(result.avg_score) if result.avg_score else None,
            'total_tasks': result.total_tasks or 0,
            'total_processed': result.total_processed or 0
        }


def compare_experiments(experiment_ids: List[UUID]) -> Dict[str, Any]:
    """
    Compare multiple experiments.
    
    Args:
        experiment_ids: List of experiment UUIDs to compare
    
    Returns:
        Dict with comparison data
    """
    with get_session() as session:
        experiments = session.query(Experiment).filter(
            Experiment.id.in_(experiment_ids)
        ).order_by(Experiment.created_at).all()
        
        if not experiments:
            return {'experiments': []}
        
        comparison = {
            'experiments': [
                {
                    'id': str(exp.id),
                    'created_at': exp.created_at.isoformat(),
                    'metric_name': exp.metric_name,
                    'average_score': exp.average_score,
                    'total_tasks': exp.total_tasks,
                    'processed_count': exp.processed_count,
                    'success_rate': exp.success_rate
                }
                for exp in experiments
            ],
            'score_trend': [exp.average_score for exp in experiments],
            'improvement': None
        }
        
        # Calculate improvement from first to last
        if len(experiments) >= 2:
            first_score = experiments[0].average_score or 0
            last_score = experiments[-1].average_score or 0
            comparison['improvement'] = last_score - first_score
        
        return comparison