"""Evaluate Predictions Metrics page - select project, metric and run evaluation."""

import importlib

import pandas as pd
import streamlit as st

from document_ia_evals.components import (
    ClientType,
    get_client,
    render_document_type_selector,
    render_project_selector,
)
from document_ia_evals.database.connection import init_db, test_db_connection
from document_ia_evals.metrics import metric_registry
from document_ia_evals.services.experiment_service import save_experiment
from document_ia_evals.services.metric_evaluation_service import (
    calculate_processing_time_stats,
    results_to_dict,
    run_metric_evaluation,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import get_project_url

# Page configuration
st.set_page_config(
    page_title="Evaluate Predictions Metrics",
    page_icon="🎯",
    layout=config.LAYOUT
)


def render_metric_selection() -> tuple[str | None, str | None]:
    """
    Render metric selection UI.
    
    Returns:
        Tuple of (selected metric name, selected document type or None)
    """
    metrics = metric_registry.list_metrics()
    
    if not metrics:
        st.warning("No metrics found. Please add metrics to the 'metrics' folder.")
        return None, None
    
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
    
    selected_document_type = None
    
    if selected_metric_label:
        selected_metric_name = metric_options[selected_metric_label]
        
        # Show metric details
        metric_info = metrics[selected_metric_name]
        
        with st.expander("📏 Metric Details", expanded=False):
            st.markdown(f"**Metric Type:** {metric_info.get('metric_type', 'standard')}")
            st.markdown(f"**Required Fields:** {', '.join(metric_info.get('require', []))}")
        
        # If metric requires document_type, show a selector
        if 'document_type' in metric_info.get('require', []):
            st.info("ℹ️ This metric requires a document type to be specified.")
            
            selected_doc_type = render_document_type_selector(
                label="Select Document Type:",
                help_text="This is required for the json_schema_extra metric to know which schema to use",
            )
            selected_document_type = selected_doc_type.value
        
        return selected_metric_name, selected_document_type
    
    return None, None


def render_processing_time_stats(observations: list[dict]) -> None:
    """Render processing time statistics table."""
    stats = calculate_processing_time_stats(observations)
    
    if not stats:
        return
    
    st.subheader("⏱️ Processing Time Statistics")
    
    stats_data = []
    for model_version, model_stats in stats.items():
        stats_data.append({
            "Model Version": model_version,
            "Mean (s)": f"{model_stats['mean_ms']/1000:.2f}",
            "Median (s)": f"{model_stats['median_ms']/1000:.2f}",
            "Std Dev (s)": f"{model_stats['std_dev_ms']/1000:.2f}",
            "Min (s)": f"{model_stats['min_ms']/1000:.2f}",
            "Max (s)": f"{model_stats['max_ms']/1000:.2f}",
            "Samples": model_stats['sample_count']
        })
    
    if stats_data:
        df = pd.DataFrame(stats_data)
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_results(results: dict, metric_name: str) -> None:
    """
    Render evaluation results using metric-specific or default renderer.
    
    Looks for a dedicated renderer in document_ia_evals.metrics.renderers first,
    then falls back to the metric module itself for backward compatibility.
    
    Args:
        results: Evaluation results dictionary
        metric_name: Name of the metric used
    """
    observations = results.get('observations', [])
    
    if not observations:
        st.warning("No observations to display.")
        return
    
    # Show processing time stats
    render_processing_time_stats(observations)
    
    st.divider()
    
    # Try to find a dedicated renderer in the metrics/renderers directory
    renderer_module_name = f"document_ia_evals.metrics.renderers.{metric_name}_renderer"
    
    try:
        renderer_module = importlib.import_module(renderer_module_name)
        
        if hasattr(renderer_module, 'render_results'):
            # Call the dedicated renderer function
            renderer_module.render_results(results)
            return
    except ImportError:
        # No dedicated renderer found, try the old location (backward compatibility)
        metric_info = metric_registry.get_metric(metric_name)
        if metric_info:
            metric_module_name = metric_info['func'].__module__
            
            try:
                metric_module = importlib.import_module(metric_module_name)
                
                if hasattr(metric_module, 'render_results'):
                    # Call the metric's custom render function (backward compatibility)
                    metric_module.render_results(results)
                    return
            except Exception as e:
                st.error(f"Error loading metric renderer: {str(e)}")
    except Exception as e:
        st.error(f"Error loading dedicated renderer: {str(e)}")
    
    # Default rendering if no custom renderer found
    st.subheader("Observations")
    for obs in observations:
        with st.expander(f"Task {obs.get('task_id')} - Model {obs.get('model_version')}", expanded=False):
            st.markdown(f"**Score:** {obs.get('score', 0):.3f}")
            if obs.get('observation'):
                st.json(obs['observation'])


def main():
    """Main evaluation page."""
    
    st.title("🎯 Evaluate Predictions Metrics")
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )
    
    st.markdown("""
    Cette page vous permet d'évaluer les métriques de prédiction sur un projet Label Studio :
    1. Sélection du projet Label Studio
    2. Sélection de la métrique
    3. Exécution de l'évaluation et visualisation des résultats
    """)
    
    # Initialize database connection
    if 'db_initialized' not in st.session_state:
        with st.spinner("Initializing database..."):
            if test_db_connection():
                init_db()
                st.session_state.db_initialized = True
            else:
                st.warning("⚠️ Database connection failed. Results will not be saved.")
                st.session_state.db_initialized = False
    
    # Initialize session state
    if 'evaluation_results' not in st.session_state:
        st.session_state.evaluation_results = None
    if 'saved_experiment_id' not in st.session_state:
        st.session_state.saved_experiment_id = None
    
    # Step 1: Select Project using component
    project_selection = render_project_selector(
        client_type=ClientType.LEGACY,
        label="Choose a project:",
        show_details=True,
        show_task_count=True,
        required=False,
        placeholder="Select a project...",
    )
    
    selected_project_id = project_selection.project_id if project_selection else None
    
    # Step 2: Select Metric
    selected_metric, selected_document_type = render_metric_selection()
    
    # Check if metric requires document_type
    requires_document_type = False
    if selected_metric:
        metric_info = metric_registry.get_metric(selected_metric)
        requires_document_type = (
            metric_info and
            'document_type' in metric_info.get('require', [])
        )
    
    # Check if all required fields are filled
    ready_to_run = (
        selected_project_id and
        selected_metric and
        (not requires_document_type or selected_document_type)
    )
    
    # Step 3: Run Evaluation
    if ready_to_run:
        st.success("✅ Ready to evaluate predictions metrics!")
        
        # Show selected configuration with Label Studio link
        project_url = get_project_url(selected_project_id)
        
        with st.expander("📋 Evaluation Configuration", expanded=True):
            st.markdown(f"**Project ID:** {selected_project_id} - 🔗 [View in Label Studio]({project_url})")
            st.markdown(f"**Metric:** {selected_metric}")
            if selected_document_type:
                st.markdown(f"**Document Type:** {selected_document_type}")
        
        # Action buttons
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            run_button = st.button("▶️ Run Evaluation", type="primary", use_container_width=True)
        
        with col2:
            save_enabled = (
                st.session_state.evaluation_results is not None and
                st.session_state.saved_experiment_id is None and
                st.session_state.get('db_initialized', False)
            )
            save_button = st.button(
                "💾 Save Results",
                type="secondary",
                use_container_width=True,
                disabled=not save_enabled
            )
        
        with col3:
            if st.session_state.saved_experiment_id:
                st.success(f"✅ Saved: {str(st.session_state.saved_experiment_id)[:8]}...")
        
        # Get the legacy client for evaluation
        client = get_client(ClientType.LEGACY)
        
        # Handle Run button
        if run_button:
            try:
                # Create progress indicators
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def on_progress(progress):
                    progress_bar.progress(progress.current / progress.total)
                    status_text.text(f"Processing task {progress.current} of {progress.total}...")
                
                with st.spinner("Running evaluation..."):
                    results = run_metric_evaluation(
                        project_id=selected_project_id,
                        metric_name=selected_metric,
                        client=client,
                        document_type=selected_document_type,
                        on_progress=on_progress
                    )
                    
                    st.session_state.evaluation_results = results_to_dict(results)
                    st.session_state.saved_experiment_id = None
                
                # Clear progress indicators
                progress_bar.empty()
                status_text.empty()
                
                st.rerun()
                
            except Exception as e:
                st.error(f"Failed to run evaluation: {str(e)}")
                st.exception(e)
        
        # Handle Save button
        if save_button:
            if st.session_state.get('db_initialized'):
                try:
                    with st.spinner("Saving to database..."):
                        results = st.session_state.evaluation_results
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
        
        # Display results if available
        if st.session_state.evaluation_results:
            results = st.session_state.evaluation_results
            
            st.divider()
            st.header("📊 Results")
            
            # Show error if present
            if results.get('error'):
                st.warning(f"⚠️ {results['error']}")
            
            # Show summary metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Tasks", results.get('total_tasks', 0))
            with col2:
                st.metric("Processed", results.get('processed_count', 0))
            with col3:
                st.metric("Skipped", results.get('skipped_count', 0))
            
            # Render detailed results
            render_results(results, selected_metric)
            
            # Link to experiment history
            if st.session_state.get('db_initialized') and st.session_state.saved_experiment_id:
                st.divider()
                if st.button("📚 View Experiment History"):
                    st.switch_page("pages/list_experiments.py")
    else:
        st.info("Please complete the configuration to continue.")
        
        missing = []
        if not selected_project_id:
            missing.append("Project")
        if not selected_metric:
            missing.append("Metric")
        if requires_document_type and not selected_document_type:
            missing.append("Document Type")
        
        if missing:
            st.warning(f"Missing: {', '.join(missing)}")


if __name__ == "__main__":
    main()
