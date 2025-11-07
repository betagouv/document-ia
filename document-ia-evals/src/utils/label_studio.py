"""Label Studio utility functions."""

import os
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