"""Experiment History page - view and manage saved experiments."""

from datetime import datetime

import pandas as pd
import streamlit as st

from document_ia_evals.database.connection import init_db, test_db_connection
from document_ia_evals.services.experiment_service import (
    delete_experiment,
    list_experiments,
    load_experiment,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.experiment_renderer import render_experiment_results

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
    
    # Get experiments
    try:
        experiments = list_experiments()
        
        if not experiments:
            st.info("No experiments found. Run an experiment and save it to see history.")
            if st.button("➕ Create New Experiment"):
                st.switch_page("pages/evaluate_metrics.py")
            st.stop()
        
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
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.subheader(f"📖 Experiment: {exp_id[:8]}...")
                with col2:
                    st.link_button("🔍 Ouvrir dans Label Studio", f"{config.LABEL_STUDIO_URL}/projects/{exp_data['project_id']}/data")
                with col3:
                    if st.button("✖️ Close", key="close_detail"):
                        del st.session_state.view_experiment_id
                        st.rerun()

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"**Metric:** {exp_data['metric_name']}")
                with col2:
                    st.markdown(f"**Created:** {format_datetime(exp_data['created_at'])}")
                with col3:
                    st.markdown(f"**Status:** {exp_data.get('status', 'unknown')}")
                
                if exp_data.get('notes'):
                    st.info(f"📝 **Notes:** {exp_data['notes']}")
                
                st.divider()
                
                # Render results using shared rendering utility
                st.subheader("📊 Detailed Results")
                render_experiment_results(exp_data, exp_data['metric_name'])
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