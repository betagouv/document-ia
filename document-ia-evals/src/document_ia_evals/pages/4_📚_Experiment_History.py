"""Experiment History page - view and manage saved experiments."""

from datetime import datetime

import pandas as pd
import streamlit as st
from document_ia_evals.components.sidebar import render_sidebar
from document_ia_evals.database.connection import init_db, test_db_connection
from document_ia_evals.metrics import metric_registry
from document_ia_evals.services.experiment_service import (
    delete_experiment,
    get_experiment_statistics,
    list_experiments,
    load_experiment,
)
from document_ia_evals.utils.config import config

# Page configuration
st.set_page_config(
    page_title=f"Experiment History | {config.APP_TITLE}",
    page_icon="📚",
    layout=config.LAYOUT
)


def format_datetime(dt_str: str) -> str:
    """Format datetime string for display."""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return dt_str


def main():
    """Main experiment history page."""
    # Render sidebar
    render_sidebar()
    
    st.title("📚 Experiment History")
    st.markdown("View and manage your saved experiment results.")
    
    # Check database connection
    if 'db_initialized' not in st.session_state:
        with st.spinner("Connecting to database..."):
            if test_db_connection():
                init_db()
                st.session_state.db_initialized = True
            else:
                st.error("⚠️ Database connection failed.")
                st.info("Make sure Docker PostgreSQL is running: `docker-compose up -d`")
                st.stop()
    
    # Filters
    st.subheader("🔍 Filters")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        project_filter = st.number_input(
            "Project ID (optional)",
            min_value=0,
            value=0,
            help="Filter by Label Studio project ID, 0 for all"
        )
    
    with col2:
        available_metrics = metric_registry.get_metric_names()
        metric_filter = st.selectbox(
            "Metric (optional)",
            options=["All"] + available_metrics,
            help="Filter by metric name"
        )
    
    with col3:
        limit = st.number_input(
            "Max results",
            min_value=10,
            max_value=200,
            value=50,
            step=10
        )
    
    st.divider()
    
    # Get experiments
    try:
        experiments = list_experiments(
            project_id=project_filter if project_filter > 0 else None,
            metric_name=metric_filter if metric_filter != "All" else None,
            limit=limit
        )
        
        if not experiments:
            st.info("No experiments found. Run an experiment and save it to see history.")
            if st.button("➕ Create New Experiment"):
                st.switch_page("pages/2_🎯_New_Experiment.py")
            st.stop()
        
        # Show statistics
        st.subheader("📊 Statistics")
        stats = get_experiment_statistics(
            project_id=project_filter if project_filter > 0 else None,
            metric_name=metric_filter if metric_filter != "All" else None
        )
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Experiments", stats['total_experiments'])
        with col2:
            avg_score = stats['average_score']
            st.metric("Average Score", f"{avg_score:.3f}" if avg_score else "N/A")
        with col3:
            st.metric("Total Tasks", stats['total_tasks'])
        with col4:
            st.metric("Processed", stats['total_processed'])
        
        st.divider()
        
        # Display experiments table
        st.subheader(f"📋 Experiments ({len(experiments)})")
        
        # Convert to DataFrame for display
        df = pd.DataFrame([
            {
                "Created": format_datetime(exp['created_at']),
                "Project ID": exp['project_id'],
                "Metric": exp['metric_name'],
                "Avg Score": f"{exp['average_score']:.3f}" if exp['average_score'] else "N/A",
                "Tasks": exp['total_tasks'],
                "Processed": exp['processed_count'],
                "Success %": f"{exp['success_rate']*100:.1f}%",
                "ID": str(exp['id'])[:8] + "...",
                "_full_id": exp['id']  # Hidden column for actions
            }
            for exp in experiments
        ])
        
        # Display table with selection
        selected_indices = st.dataframe(
            df.drop(columns=['_full_id']),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
        )
        
        # Actions for selected experiments
        if hasattr(selected_indices, 'selection') and selected_indices.selection.rows:
            selected_rows = selected_indices.selection.rows
            selected_exp_ids = [df.iloc[i]['_full_id'] for i in selected_rows]
            
            st.divider()
            st.subheader(f"🎯 Actions ({len(selected_exp_ids)} selected)")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if len(selected_exp_ids) == 1 and st.button("👁️ View Details", use_container_width=True):
                    st.session_state.view_experiment_id = selected_exp_ids[0]
                    st.rerun()
                        
            # with col2:
            #     if st.button("📥 Export JSON", use_container_width=True):
            #         st.info("Export functionality coming soon")
            
            with col3:
                if st.button("🗑️ Delete", type="secondary", use_container_width=True):
                    st.session_state.delete_confirmation = selected_exp_ids
                    st.rerun()
        
        # View experiment details
        if 'view_experiment_id' in st.session_state:
            st.divider()
            exp_id = st.session_state.view_experiment_id
            
            with st.spinner("Loading experiment details..."):
                exp_data = load_experiment(exp_id)
            
            if exp_data:
                # Header with close button
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(f"📖 Experiment: {exp_id[:8]}...")
                    st.link_button("Ouvrir dans label studio", f"{config.LABEL_STUDIO_URL}/projects/{exp_data['project_id']}/data")
                with col2:
                    if st.button("✖️ Close", key="close_detail"):
                        del st.session_state.view_experiment_id
                        st.rerun()
                
                # Experiment metadata
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Project ID", exp_data['project_id'])
                with col2:
                    st.metric("Total Tasks", exp_data['total_tasks'])
                with col3:
                    score = exp_data.get('average_score')
                    st.metric("Average Score", f"{score:.3f}" if score else "N/A")
                
                st.markdown(f"**Metric:** {exp_data['metric_name']}")
                st.markdown(f"**Created:** {format_datetime(exp_data['created_at'])}")
                st.markdown(f"**Status:** {exp_data.get('status', 'unknown')}")
                
                if exp_data.get('notes'):
                    st.info(f"📝 **Notes:** {exp_data['notes']}")
                
                st.divider()
                
                # Render results using metric's render function
                st.subheader("📊 Detailed Results")
                
                metric_info = metric_registry.get_metric(exp_data['metric_name'])
                if metric_info:
                    metric_module_name = metric_info['func'].__module__
                    
                    try:
                        import importlib
                        metric_module = importlib.import_module(metric_module_name)
                        
                        if hasattr(metric_module, 'render_results'):
                            # Call the metric's render function with loaded data
                            metric_module.render_results(exp_data)
                        else:
                            # Fallback: show observations
                            st.info("This metric doesn't have a custom render function")
                            for idx, obs in enumerate(exp_data.get('observations', []), 1):
                                with st.expander(f"Observation {idx}", expanded=False):
                                    st.json(obs.get('observation', '{}'))
                    except Exception as e:
                        st.error(f"Error rendering results: {str(e)}")
                        st.exception(e)
                        # Fallback display
                        with st.expander("Raw Data", expanded=False):
                            st.json(exp_data)
                else:
                    st.warning(f"Metric '{exp_data['metric_name']}' not found in registry")
                    with st.expander("Raw Data", expanded=True):
                        st.json(exp_data)
            else:
                st.error("Experiment not found")
                del st.session_state.view_experiment_id
                st.rerun()
        
        # Delete confirmation
        if 'delete_confirmation' in st.session_state:
            st.divider()
            exp_ids = st.session_state.delete_confirmation
            
            st.warning(f"⚠️ Are you sure you want to delete {len(exp_ids)} experiment(s)?")
            st.markdown("**This action cannot be undone.**")
            
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("✅ Yes, Delete", type="primary"):
                    deleted_count = 0
                    for exp_id in exp_ids:
                        if delete_experiment(exp_id):
                            deleted_count += 1
                    
                    st.success(f"Deleted {deleted_count} experiment(s)")
                    del st.session_state.delete_confirmation
                    st.rerun()
            
            with col2:
                if st.button("❌ Cancel"):
                    del st.session_state.delete_confirmation
                    st.rerun()
    
    except Exception as e:
        st.error(f"Error loading experiments: {str(e)}")
        st.exception(e)


if __name__ == "__main__":
    main()