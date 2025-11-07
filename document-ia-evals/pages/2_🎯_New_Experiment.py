"""New Experiment page - select project and metric to create an experiment."""

import os
import streamlit as st
from dotenv import load_dotenv
from label_studio_sdk import Client
from typing import Optional

from document_ia_evals.components.sidebar import render_sidebar
from document_ia_evals.utils.config import Config
from metrics import metric_registry

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title=f"New Experiment | {Config.APP_TITLE}",
    page_icon="🎯",
    layout=Config.LAYOUT
)


def get_label_studio_client() -> Optional[Client]:
    """Create a Label Studio client using environment variables."""
    url = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
    api_key = os.getenv("LABEL_STUDIO_API_KEY")
    
    if not api_key:
        st.warning("⚠️ LABEL_STUDIO_API_KEY environment variable is not set.")
        return None
    
    try:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False
        client = Client(url=url, api_key=api_key, session=session)
        return client
    except Exception as e:
        st.error(f"Failed to connect to Label Studio: {str(e)}")
        return None


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
    
    # Get Label Studio client
    client = get_label_studio_client()
    
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
    else:
        st.session_state.selected_metric = None
    
    # Step 3: Create Experiment
    st.header("3️⃣ Start Experiment")
    
    if st.session_state.selected_project and st.session_state.selected_metric:
        st.success("✅ Ready to create experiment!")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("▶️ Run Experiment", type="primary", use_container_width=True):
                # Navigate to experiment results page with URL parameters
                project_id = st.session_state.selected_project
                metric_name = st.session_state.selected_metric
                st.switch_page(f"pages/3_📈_Experiment_Results.py")
    else:
        st.info("Please select both a project and a metric to continue.")
        
        missing = []
        if not st.session_state.selected_project:
            missing.append("Project")
        if not st.session_state.selected_metric:
            missing.append("Metric")
        
        st.warning(f"Missing: {', '.join(missing)}")


if __name__ == "__main__":
    main()