"""Experiment Results page - run metric on selected project and display results."""

import os
import streamlit as st
import json
from dotenv import load_dotenv
from label_studio_sdk import Client
from typing import Optional, Any, Dict

from src.components.sidebar import render_sidebar
from src.utils.config import Config
from metrics import metric_registry

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title=f"Experiment Results | {Config.APP_TITLE}",
    page_icon="📈",
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


def extract_raw_api_response(results):
    """Extract data from results where from_name is raw_api_response."""
    for result in results:
        if result.get('from_name') == 'raw_api_response':
            try:
                text = result['value']['text']
                if isinstance(text, list):
                    text = text[0]
                if isinstance(text, str):
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
                return text
            except Exception:
                return None
    return None


def run_experiment(project_id: int, metric_name: str, client: Client) -> Dict[str, Any]:
    """
    Run the experiment: fetch data from Label Studio and apply the metric.
    
    Args:
        project_id: Label Studio project ID
        metric_name: Name of the metric to apply
        client: Label Studio client
    
    Returns:
        Dictionary with experiment results
    """
    # Get the metric
    metric_info = metric_registry.get_metric(metric_name)
    if not metric_info:
        raise ValueError(f"Metric '{metric_name}' not found in registry")
    
    metric_func = metric_info['func']
    required_fields = metric_info.get('require', [])
    
    # Get the project
    try:
        project = client.get_project(project_id)
        project_params = project.get_params()
    except Exception as e:
        raise ValueError(f"Failed to get project {project_id}: {str(e)}")
    
    # Fetch tasks
    with st.spinner("Fetching tasks from Label Studio..."):
        tasks = project.get_tasks()
    
    if not tasks:
        return {
            "project_id": project_id,
            "project_title": project_params.get('title', 'Unknown'),
            "metric_name": metric_name,
            "observations": [],
            "error": "No tasks found in project"
        }
    
    # Process tasks
    observations = []
    processed_count = 0
    skipped_count = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, task in enumerate(tasks):
        task_id = task.get('id', 'Unknown')
        
        # Update progress
        progress = (idx + 1) / len(tasks)
        progress_bar.progress(progress)
        status_text.text(f"Processing task {idx + 1} of {len(tasks)}...")
        
        # Extract ground truth
        ground_truth = None
        for annotation in task.get('annotations', []):
            if annotation.get('ground_truth'):
                ground_truth = extract_raw_api_response(annotation.get('result', []))
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
            pred_data = extract_raw_api_response(prediction.get('result', []))
            
            if pred_data is None:
                skipped_count += 1
                continue
            
            # Run the metric
            try:
                # Prepare metric inputs based on required fields
                metric_inputs = {}
                
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
                    metric_inputs['query'] = task.get('data', {})
                
                # Run metric
                score, observation_json, output = metric_func(**metric_inputs)
                
                observations.append({
                    "task_id": task_id,
                    "model_version": model_version,
                    "prediction_id": prediction.get('id', 'Unknown'),
                    "score": score,
                    "observation": observation_json,
                    "output": output
                })
                
                processed_count += 1
            
            except Exception as e:
                st.warning(f"Error processing task {task_id}: {str(e)}")
                observations.append({
                    "task_id": task_id,
                    "model_version": model_version,
                    "prediction_id": prediction.get('id', 'Unknown'),
                    "score": 0.0,
                    "observation": json.dumps({"error": str(e)}),
                    "output": None
                })
                skipped_count += 1
    
    # Clear progress indicators
    progress_bar.empty()
    status_text.empty()
    
    return {
        "project_id": project_id,
        "project_title": project_params.get('title', 'Unknown'),
        "metric_name": metric_name,
        "observations": observations,
        "total_tasks": len(tasks),
        "processed_count": processed_count,
        "skipped_count": skipped_count
    }


def main():
    """Main experiment results page."""
    # Render sidebar
    render_sidebar()
    
    st.title("📈 Experiment Results")
    
    # Check if we have selection in session state
    if 'selected_project' not in st.session_state or 'selected_metric' not in st.session_state:
        st.warning("⚠️ No experiment selected. Please start from the New Experiment page.")
        if st.button("Go to New Experiment"):
            st.switch_page("pages/3_🎯_New_Experiment.py")
        st.stop()
    
    project_id = st.session_state.selected_project
    metric_name = st.session_state.selected_metric
    
    if not project_id or not metric_name:
        st.warning("⚠️ Incomplete experiment configuration.")
        if st.button("Go to New Experiment"):
            st.switch_page("pages/3_🎯_New_Experiment.py")
        st.stop()
    
    # Display experiment info
    st.markdown(f"**Project ID:** {project_id}")
    st.markdown(f"**Metric:** {metric_name}")
    
    # Back button
    if st.button("⬅️ Back to New Experiment"):
        st.switch_page("pages/3_🎯_New_Experiment.py")
    
    st.divider()
    
    # Get Label Studio client
    client = get_label_studio_client()
    if not client:
        st.stop()
    
    # Run experiment button
    if 'experiment_results' not in st.session_state:
        st.session_state.experiment_results = None
    
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("▶️ Run Experiment", type="primary", use_container_width=True):
            try:
                with st.spinner("Running experiment..."):
                    results = run_experiment(project_id, metric_name, client)
                    st.session_state.experiment_results = results
            except Exception as e:
                st.error(f"Failed to run experiment: {str(e)}")
                st.exception(e)
    
    with col2:
        if st.session_state.experiment_results:
            if st.button("🔄 Refresh Results", use_container_width=True):
                try:
                    with st.spinner("Running experiment..."):
                        results = run_experiment(project_id, metric_name, client)
                        st.session_state.experiment_results = results
                except Exception as e:
                    st.error(f"Failed to run experiment: {str(e)}")
    
    # Display results if available
    if st.session_state.experiment_results:
        results = st.session_state.experiment_results
        
        st.header("📊 Results")
        
        # Show summary
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Tasks", results.get('total_tasks', 0))
        with col2:
            st.metric("Processed", results.get('processed_count', 0))
        with col3:
            st.metric("Skipped", results.get('skipped_count', 0))
        
        st.divider()
        
        # Get metric info and call its render function if available
        metric_info = metric_registry.get_metric(metric_name)
        if metric_info:
            metric_module_name = metric_info['func'].__module__
            
            # Try to import and call the render function
            try:
                import importlib
                metric_module = importlib.import_module(metric_module_name)
                
                if hasattr(metric_module, 'render_results'):
                    # Call the metric's custom render function
                    metric_module.render_results(results)
                else:
                    # Default rendering
                    st.subheader("Observations")
                    for obs in results.get('observations', []):
                        with st.expander(f"Task {obs.get('task_id')} - Model {obs.get('model_version')}", expanded=False):
                            st.markdown(f"**Score:** {obs.get('score', 0):.3f}")
                            if obs.get('observation'):
                                st.json(obs['observation'])
            except Exception as e:
                st.error(f"Error rendering results: {str(e)}")
                # Fallback to default rendering
                st.subheader("Observations")
                for obs in results.get('observations', []):
                    with st.expander(f"Task {obs.get('task_id')} - Model {obs.get('model_version')}", expanded=False):
                        st.markdown(f"**Score:** {obs.get('score', 0):.3f}")
                        if obs.get('observation'):
                            st.json(obs['observation'])


if __name__ == "__main__":
    main()