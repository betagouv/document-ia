"""Label Studio project selector smart component."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import streamlit as st

from document_ia_evals.utils.label_studio import (
    get_label_studio_client,
    get_label_studio_client_legacy,
    get_project_url,
)


class ClientType(Enum):
    """Label Studio client type."""
    SDK = "sdk"  # LabelStudio (modern SDK)
    LEGACY = "legacy"  # Client (legacy)


@dataclass
class ProjectSelection:
    """Result of project selection."""
    project_id: int
    project_title: str
    task_count: int | None = None


def _get_projects_sdk(client: Any) -> list[dict[str, Any]]:
    """Get projects using SDK client."""
    projects = client.projects.list()
    return [
        {
            "id": p.id,
            "title": p.title or f"Project {p.id}",
            "description": p.description,
            "created_at": None,
            "task_number": None,
        }
        for p in projects
    ]


def _get_projects_legacy(client: Any) -> list[dict[str, Any]]:
    """Get projects using legacy client."""
    projects = client.list_projects()
    return [
        {
            "id": p.get_params()["id"],
            "title": p.get_params().get("title") or f"Project {p.get_params()['id']}",
            "description": p.get_params().get("description"),
            "created_at": p.get_params().get("created_at"),
            "task_number": p.get_params().get("task_number", 0),
        }
        for p in projects
    ]


def _get_task_count_sdk(client: Any, project_id: int) -> int:
    """Get task count using SDK client."""
    tasks = [task for task in client.tasks.list(project=project_id, fields='all')]
    return len(tasks)


def render_project_selector(
    client_type: ClientType = ClientType.SDK,
    label: str = "Sélectionnez un projet Label Studio",
    show_details: bool = True,
    show_task_count: bool = True,
    show_link: bool = False,
    required: bool = True,
    placeholder: str | None = None,
) -> ProjectSelection | None:
    """
    Render Label Studio project selection component.
    
    This is a smart component that fetches projects from Label Studio
    and handles all display logic. Supports both SDK and legacy clients.
    
    Args:
        client_type: Type of Label Studio client to use (SDK or LEGACY)
        label: Label for the selectbox
        show_details: Whether to show project details in an expander
        show_task_count: Whether to fetch and show task count (SDK only)
        show_link: Whether to show a link to the project
        required: If False, allows no selection (shows placeholder)
        placeholder: Placeholder text when no selection (only when required=False)
    
    Returns:
        ProjectSelection with selected project info, or None if error/no projects/no selection
    """
    try:
        # Get appropriate client
        if client_type == ClientType.SDK:
            client = get_label_studio_client()
            projects = _get_projects_sdk(client)
        else:
            client = get_label_studio_client_legacy()
            projects = _get_projects_legacy(client)
        
        if not projects:
            st.warning("⚠️ No Label Studio projects found")
            return None
        
        # Project selector
        project_options = {p["id"]: p["title"] for p in projects}
        
        selectbox_kwargs: dict[str, Any] = {
            "label": label,
            "options": list(project_options.keys()),
            "format_func": lambda x: project_options[x],
        }
        
        if required:
            selectbox_kwargs["index"] = 0
        else:
            selectbox_kwargs["index"] = None
            selectbox_kwargs["placeholder"] = placeholder or "Select a project..."
        
        selected_project_id: int | None = st.selectbox(**selectbox_kwargs)
        
        if selected_project_id is None:
            return None
        
        # Get selected project details
        selected_project = next(p for p in projects if p["id"] == selected_project_id)
        
        # Get task count
        task_count = None
        if show_task_count:
            if client_type == ClientType.SDK:
                task_count = _get_task_count_sdk(client, selected_project_id)
            else:
                task_count = selected_project.get("task_number")
        
        # Display project details
        if show_details:
            with st.expander("Détails du projet"):
                st.write(f"**Title:** {selected_project['title']}")
                st.write(f"**Description:** {selected_project['description'] or 'N/A'}")
                if task_count is not None:
                    st.write(f"**Number of tasks:** {task_count}")
                if selected_project.get("created_at"):
                    st.write(f"**Created:** {selected_project['created_at']}")
        
        # Show link if requested
        if show_link:
            project_url = get_project_url(selected_project_id)
            st.markdown(f"🔗 [View in Label Studio]({project_url})")
        
        return ProjectSelection(
            project_id=selected_project_id,
            project_title=selected_project["title"],
            task_count=task_count,
        )
    
    except Exception as e:
        st.error(f"❌ Failed to fetch Label Studio projects: {e}")
        return None


def get_client(client_type: ClientType) -> Any:
    """
    Get the Label Studio client based on client type.
    
    Args:
        client_type: Type of client to get
    
    Returns:
        Label Studio client instance
    """
    if client_type == ClientType.SDK:
        return get_label_studio_client()
    return get_label_studio_client_legacy()

