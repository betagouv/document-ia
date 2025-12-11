"""Export Dataset page - download Label Studio project tasks as JSON."""

import json
from typing import Any, cast

import streamlit as st

from document_ia_evals.components import (
    ClientType,
    render_project_selector,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import fetch_project_tasks, get_project_url

# Page configuration
st.set_page_config(
    page_title="Export label studio Dataset",
    page_icon="📥",
    layout=cast(Any, config.LAYOUT)
)


def main():
    """Main export dataset page."""
    
    st.title("📥 Export Dataset")
    st.caption(
        f"Using: Label Studio URL: {config.LABEL_STUDIO_URL}"
    )
    
    st.markdown("""
    Cette page vous permet d'exporter les tâches d'un projet Label Studio :
    1. Sélection du projet Label Studio
    2. Téléchargement du fichier JSON contenant toutes les tâches
    """)
    
    # Initialize session state
    if 'export_data' not in st.session_state:
        st.session_state.export_data = None
    if 'export_project_id' not in st.session_state:
        st.session_state.export_project_id = None
    
    # Step 1: Select Project using component
    project_selection = render_project_selector(
        client_type=ClientType.LEGACY,
        label="Choose a project:",
        show_details=True,
        show_task_count=True,
        required=False,
        placeholder="Select a project to export...",
    )
    
    selected_project_id = project_selection.project_id if project_selection else None
    
    # Check if ready to export
    if selected_project_id:
        st.success("✅ Ready to export dataset!")
        
        # Show selected configuration with Label Studio link
        project_url = get_project_url(selected_project_id)
        
        with st.expander("📋 Export Configuration", expanded=True):
            st.markdown(f"**Project ID:** {selected_project_id} - 🔗 [View in Label Studio]({project_url})")
        
        # Export button
        col1, col2 = st.columns([1, 3])
        
        with col1:
            export_button = st.button("📥 Export Tasks", type="primary", use_container_width=True)
        
        # Handle Export button
        if export_button:
            try:
                with st.spinner("Fetching tasks from Label Studio..."):
                    tasks: list[dict[str, Any]] = fetch_project_tasks(selected_project_id)
                    
                    # Store in session state
                    st.session_state.export_data = tasks
                    st.session_state.export_project_id = selected_project_id
                
                st.success(f"✅ Successfully fetched {len(tasks)} task(s)!")
                st.rerun()
                
            except Exception as e:
                st.error(f"Failed to export tasks: {str(e)}")
                st.exception(e)
        
        # Display download button if data is available
        if (st.session_state.export_data is not None and 
            st.session_state.export_project_id == selected_project_id):
            
            tasks: list[dict[str, Any]] = st.session_state.export_data
            
            st.divider()
            st.header("📊 Export Results")
            
            # Show summary
            st.metric("Total Tasks Exported", len(tasks))
            
            # Prepare JSON data
            json_data = json.dumps(tasks, indent=2, ensure_ascii=False)
            
            # Download button
            st.download_button(
                label="💾 Download JSON",
                data=json_data,
                file_name=f"project_{selected_project_id}_tasks.json",
                mime="application/json",
                use_container_width=True
            )
            
            # Show preview
            with st.expander("👀 Preview (first 3 tasks)", expanded=False):
                preview_tasks: list[dict[str, Any]] = tasks[:3]
                st.json(preview_tasks)
            
            # Show statistics
            with st.expander("📈 Dataset Statistics", expanded=False):
                # Count tasks with annotations
                annotated_tasks = sum(1 for task in tasks if task.get('annotations'))
                completed_tasks = sum(
                    1 for task in tasks 
                    if task.get('annotations') and any(
                        ann.get('completed_by') for ann in task['annotations']
                    )
                )
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Tasks", len(tasks))
                with col2:
                    st.metric("With Annotations", annotated_tasks)
                with col3:
                    st.metric("Completed", completed_tasks)
    else:
        st.info("Please select a project to export.")


if __name__ == "__main__":
    main()