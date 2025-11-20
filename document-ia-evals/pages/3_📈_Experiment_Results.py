"""Experiment Results page - run metric on selected project and display results."""

import os
import streamlit as st
import json
from dotenv import load_dotenv
from label_studio_sdk import Client
from typing import Optional, Any, Dict
from uuid import UUID

from document_ia_evals.components.sidebar import render_sidebar
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import annotation_results_to_dict, get_project_url
from metrics import metric_registry
from document_ia_evals.services.experiment_service import save_experiment
from document_ia_evals.database.connection import test_db_connection, init_db

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title=f"Experiment Results | {config.APP_TITLE}",
    page_icon="📈",
    layout=config.LAYOUT
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
                ground_truth, ground_truth_meta = annotation_results_to_dict(annotation.get('result', []))
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
                
                # Handle document_type parameter (for json_schema_extra metric)
                if 'document_type' in required_fields:
                    # Try to get document_type from session state first
                    document_type = st.session_state.get('selected_document_type')
                    
                    # If not in session state, try to infer from data
                    if not document_type:
                        # Try to get from prediction data
                        if isinstance(pred_data, dict) and 'type' in pred_data:
                            document_type = pred_data['type']
                        # Try to get from ground truth data
                        elif isinstance(ground_truth, dict) and 'type' in ground_truth:
                            document_type = ground_truth['type']
                        # Try to get from task data
                        elif 'document_type' in task.get('data', {}):
                            document_type = task['data']['document_type']
                    
                    if document_type:
                        metric_inputs['document_type'] = document_type
                    else:
                        # Log warning but continue - metric will handle missing document_type
                        st.warning(f"⚠️ Could not infer document_type for task {task_id}. Metric may fail.")
                
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
                st.warning(f"Error processing task {task_id}: {str(e)}")
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
    
    # Check database connection
    if 'db_initialized' not in st.session_state:
        with st.spinner("Initializing database..."):
            if test_db_connection():
                init_db()
                st.session_state.db_initialized = True
            else:
                st.error("⚠️ Database connection failed. Results will not be saved.")
                st.info("Make sure Docker PostgreSQL is running: `docker-compose up -d`")
    
    # Check if we have selection in session state
    if 'selected_project' not in st.session_state or 'selected_metric' not in st.session_state:
        st.warning("⚠️ No experiment selected. Please start from the New Experiment page.")
        if st.button("Go to New Experiment"):
            st.switch_page("pages/2_🎯_New_Experiment.py")
        st.stop()
    
    project_id = st.session_state.selected_project
    metric_name = st.session_state.selected_metric
    
    if not project_id or not metric_name:
        st.warning("⚠️ Incomplete experiment configuration.")
        if st.button("Go to New Experiment"):
            st.switch_page("pages/2_🎯_New_Experiment.py")
        st.stop()
    
    # Display experiment info with Label Studio link
    project_url = get_project_url(project_id)
    st.markdown(f"**Project ID:** {project_id} - 🔗 [View in Label Studio]({project_url})")
    st.markdown(f"**Metric:** {metric_name}")
    
    # Back button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("⬅️ Back"):
            st.switch_page("pages/2_🎯_New_Experiment.py")
    with col2:
        if st.session_state.get('db_initialized') and 'saved_experiment_id' in st.session_state:
            if st.button("📚 View History"):
                st.switch_page("pages/4_📚_Experiment_History.py")
    
    st.divider()
    
    # Get Label Studio client
    client = get_label_studio_client()
    if not client:
        st.stop()
    
    # Initialize session state
    if 'experiment_results' not in st.session_state:
        st.session_state.experiment_results = None
    if 'saved_experiment_id' not in st.session_state:
        st.session_state.saved_experiment_id = None
    
    # Run experiment button
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("▶️ Run Experiment", type="primary", use_container_width=True):
            try:
                with st.spinner("Running experiment..."):
                    results = run_experiment(project_id, metric_name, client)
                    st.session_state.experiment_results = results
                    st.session_state.saved_experiment_id = None  # Reset saved ID
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to run experiment: {str(e)}")
                st.exception(e)
    
    with col2:
        if st.session_state.experiment_results and not st.session_state.saved_experiment_id:
            if st.button("💾 Save Results", type="secondary", use_container_width=True):
                if st.session_state.get('db_initialized'):
                    try:
                        with st.spinner("Saving to database..."):
                            results = st.session_state.experiment_results
                            experiment_id = save_experiment(
                                project_id=results['project_id'],
                                metric_name=results['metric_name'],
                                observations_data=results['observations'],
                                total_tasks=results['total_tasks']
                            )
                            st.session_state.saved_experiment_id = experiment_id
                            st.success(f"✅ Experiment saved! ID: {str(experiment_id)[:8]}...")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save experiment: {str(e)}")
                        st.exception(e)
                else:
                    st.error("Database not initialized. Check connection.")
    
    with col3:
        if st.session_state.saved_experiment_id:
            st.success(f"✅ Saved: {str(st.session_state.saved_experiment_id)[:8]}...")
    
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
        
        # Calculate and display processing time statistics by model version
        observations = results.get('observations', [])
        if observations:
            # Group processing times by model version
            processing_times_by_model = {}
            for obs in observations:
                model_version = obs.get('model_version', 'Unknown')
                processing_time = obs.get('processing_time_ms')
                if processing_time is not None:
                    if model_version not in processing_times_by_model:
                        processing_times_by_model[model_version] = []
                    processing_times_by_model[model_version].append(processing_time)
            
            # Display processing time statistics if available
            if processing_times_by_model:
                st.subheader("⏱️ Processing Time Statistics")
                import pandas as pd
                import numpy as np
                
                stats_data = []
                for model_version, times in sorted(processing_times_by_model.items()):
                    if times:
                        stats_data.append({
                            "Model Version": model_version,
                            "Mean (s)": f"{np.mean(times)/1000:.2f}",
                            "Median (s)": f"{np.median(times)/1000:.2f}",
                            "Std Dev (s)": f"{np.std(times)/1000:.2f}",
                            "Min (s)": f"{min(times)/1000:.2f}",
                            "Max (s)": f"{max(times)/1000:.2f}",
                            "Samples": len(times)
                        })
                
                if stats_data:
                    df = pd.DataFrame(stats_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
        
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