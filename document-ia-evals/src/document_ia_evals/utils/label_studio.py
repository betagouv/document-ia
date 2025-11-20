"""Label Studio utility functions."""

import json
import os
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()


def get_label_studio_url() -> str:
    """Get the base Label Studio URL from environment."""
    url = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
    # Remove trailing slash if present
    return url.rstrip('/')


def get_project_url(project_id: int) -> str:
    """
    Generate Label Studio project data URL.
    
    Args:
        project_id: Label Studio project ID
    
    Returns:
        str: URL to the project's data page
    
    Example:
        >>> get_project_url(10)
        'https://labeling.document-ia.beta.gouv.fr/projects/10/data'
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/data"


def get_task_url(project_id: int, task_id: int) -> str:
    """
    Generate Label Studio task URL.
    
    Args:
        project_id: Label Studio project ID
        task_id: Task ID
    
    Returns:
        str: URL to the specific task
    
    Example:
        >>> get_task_url(10, 123)
        'https://labeling.document-ia.beta.gouv.fr/projects/10/data?task=123'
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/data?task={task_id}"


def get_project_settings_url(project_id: int) -> str:
    """
    Generate Label Studio project settings URL.
    
    Args:
        project_id: Label Studio project ID
    
    Returns:
        str: URL to the project's settings page
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/settings"



METADATA_KEY = '__metadata__'
def dict_to_annotation_result(data: dict[str, Any], metadata: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Convert workflow result data to Label Studio annotation structure."""
    results: list[dict[str, Any]] = []
    
    for field_name, value in data.items():
        if value is not None:
            results.append({
                'value': {'text': [str(value)]},
                'from_name': field_name,
                'to_name': 'pdf',
                'type': 'textarea',
                'readonly': False
            })
    if metadata is not None:
        results.append({
            'value': {'text': [json.dumps(metadata)]},
            'from_name': METADATA_KEY,
            'to_name': 'pdf',
            'type': 'textarea',
            'readonly': True
        })
        

    
    return results

def annotation_results_to_dict(annotation_results: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Convert Label Studio annotation results back to a dictionary.
    
    This is the reverse operation of dict_to_annotation_result.
    
    Args:
        annotation_results: List of Label Studio annotation result objects
        
    Returns:
        dict: Dictionary mapping field names to their values
        
    Example:
        >>> results = [
        ...     {
        ...         'value': {'text': ['John Doe']},
        ...         'from_name': 'name',
        ...         'to_name': 'pdf',
        ...         'type': 'textarea'
        ...     }
        ... ]
        >>> annotation_results_to_dict(results)
        {'name': 'John Doe'}
    """
    data: dict[str, Any] = {}
    metadata: dict[str, Any] | None = None
    for result in annotation_results:
        field_name = result.get('from_name')
                    
        # Extract the value from the nested structure
        value_obj = result.get('value', {})
        text_list = value_obj.get('text', [])
        
        if field_name and text_list:
            if field_name == METADATA_KEY:
                metadata = json.loads(text_list[0])
            else:
                data[field_name] = text_list[0]
    
    return data, metadata

