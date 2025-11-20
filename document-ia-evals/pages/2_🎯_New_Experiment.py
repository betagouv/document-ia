"""New Experiment page - select project and metric to create an experiment."""

import os
from document_ia_evals.utils.label_studio import get_label_studio_client_legacy
import streamlit as st
from dotenv import load_dotenv
from typing import Optional

from document_ia_evals.components.sidebar import render_sidebar
from document_ia_evals.utils.config import config
from metrics import metric_registry

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title=f"New Experiment | {config.APP_TITLE}",
    page_icon="🎯",
    layout=config.LAYOUT
)




def main():
    """Main experiment selection page."""
    # Render sidebar
    render_sidebar()
    
    st.title("🎯 Create New Experiment")
    st.markdown("Select a Label Studio project and a metric to evaluate.")
    
    # Initialize session state
    if 'selected_project' not in st.session_state:
        st.session_state.selected_project = None
    if 'selected_metric' not in st.session_state:
        st.session_state.selected_metric = None
    if 'selected_document_type' not in st.session_state:
        st.session_state.selected_document_type = None
    
    # Get Label Studio client
    client = get_label_studio_client_legacy()
    
    if not client:
        st.stop()
    
    # Step 1: Select Project
    st.header("1️⃣ Select Label Studio Project")
    
    try:
        with st.spinner("Fetching projects from Label Studio..."):
            projects = client.list_projects()
        
        if not projects:
            st.info("No projects found in your Label Studio instance.")
            st.stop()
        
        # Create project selection dropdown
        project_options = {
            f"{p.get_params()['title']} (ID: {p.get_params()['id']})": p.get_params()['id']
            for p in projects
        }
        
        selected_project_label = st.selectbox(
            "Choose a project:",
            options=list(project_options.keys()),
            index=None,
            placeholder="Select a project..."
        )
        
        if selected_project_label:
            selected_project_id = project_options[selected_project_label]
            st.session_state.selected_project = selected_project_id
            
            # Show project details
            selected_project = next(
                (p for p in projects if p.get_params()['id'] == selected_project_id),
                None
            )
            
            if selected_project:
                params = selected_project.get_params()
                
                with st.expander("📊 Project Details", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Project ID:** {params['id']}")
                        st.markdown(f"**Total Tasks:** {params.get('task_number', 0)}")
                    with col2:
                        st.markdown(f"**Created:** {params.get('created_at', 'N/A')}")
                        if params.get('description'):
                            st.markdown(f"**Description:** {params['description']}")
        else:
            st.session_state.selected_project = None
    
    except Exception as e:
        st.error(f"Error fetching projects: {str(e)}")
        st.stop()
    
    # Step 2: Select Metric
    st.header("2️⃣ Select Evaluation Metric")
    
    metrics = metric_registry.list_metrics()
    
    if not metrics:
        st.warning("No metrics found. Please add metrics to the 'metrics' folder.")
        st.stop()
    
    # Create metric selection dropdown
    metric_options = {
        f"{info['name']}: {info['description']}": info['name']
        for name, info in metrics.items()
    }
    
    selected_metric_label = st.selectbox(
        "Choose a metric:",
        options=list(metric_options.keys()),
        index=None,
        placeholder="Select a metric..."
    )
    
    if selected_metric_label:
        selected_metric_name = metric_options[selected_metric_label]
        st.session_state.selected_metric = selected_metric_name
        
        # Show metric details
        metric_info = metrics[selected_metric_name]
        
        with st.expander("📏 Metric Details", expanded=False):
            st.markdown(f"**Metric Type:** {metric_info.get('metric_type', 'standard')}")
            st.markdown(f"**Required Fields:** {', '.join(metric_info.get('require', []))}")
        
        # If metric requires document_type, show a selector
        if 'document_type' in metric_info.get('require', []):
            st.info("ℹ️ This metric requires a document type to be specified.")
            
            from document_ia_schemas import SupportedDocumentType
            
            document_type_options = {
                f"{dt.value}": dt.value
                for dt in SupportedDocumentType
            }
            
            selected_doc_type = st.selectbox(
                "Select Document Type:",
                options=list(document_type_options.keys()),
                index=None,
                placeholder="Choose a document type...",
                help="This is required for the json_schema_extra metric to know which schema to use"
            )
            
            if selected_doc_type:
                st.session_state.selected_document_type = document_type_options[selected_doc_type]
            else:
                st.session_state.selected_document_type = None
        else:
            # Clear document type if metric doesn't require it
            st.session_state.selected_document_type = None
    else:
        st.session_state.selected_metric = None
        st.session_state.selected_document_type = None
    
    # Step 3: Create Experiment
    st.header("3️⃣ Start Experiment")
    
    # Check if metric requires document_type
    metric_info = None
    if st.session_state.selected_metric:
        metric_info = metrics.get(st.session_state.selected_metric)
    
    requires_document_type = (
        metric_info and
        'document_type' in metric_info.get('require', [])
    )
    
    # Check if all required fields are filled
    ready_to_run = (
        st.session_state.selected_project and
        st.session_state.selected_metric and
        (not requires_document_type or st.session_state.selected_document_type)
    )
    
    if ready_to_run:
        st.success("✅ Ready to create experiment!")
        
        # Show selected configuration
        with st.expander("📋 Experiment Configuration", expanded=True):
            st.markdown(f"**Project ID:** {st.session_state.selected_project}")
            st.markdown(f"**Metric:** {st.session_state.selected_metric}")
            if st.session_state.selected_document_type:
                st.markdown(f"**Document Type:** {st.session_state.selected_document_type}")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("▶️ Run Experiment", type="primary", use_container_width=True):
                # Navigate to experiment results page
                st.switch_page(f"pages/3_📈_Experiment_Results.py")
    else:
        st.info("Please complete the configuration to continue.")
        
        missing = []
        if not st.session_state.selected_project:
            missing.append("Project")
        if not st.session_state.selected_metric:
            missing.append("Metric")
        if requires_document_type and not st.session_state.selected_document_type:
            missing.append("Document Type")
        
        if missing:
            st.warning(f"Missing: {', '.join(missing)}")


if __name__ == "__main__":
    main()