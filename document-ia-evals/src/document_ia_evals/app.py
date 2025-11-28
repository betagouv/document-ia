"""Main Streamlit application entry point."""

import streamlit as st

from document_ia_evals.utils.config import config

# Initialize configuration
config.ensure_directories()

# Page configuration
st.set_page_config(
    page_title=config.APP_TITLE,
    page_icon=config.PAGE_ICON,
    layout=config.LAYOUT,
    initial_sidebar_state="expanded"
)


def main():
    """Main application function."""

    st.logo('src/document_ia_evals/assets/logo.svg', link="https://beta.gouv.fr/startups/document-ia", size="large")

    pages = {
        "Home": [
            st.Page("pages/home.py", title="🏠 Home"),
        ],
        "API Playground": [
            st.Page("pages/run_api_workflow.py", title="📄 Execute Workflow"),
            st.Page("pages/retrieve_api_execution.py", title="🔍 Retrieve Past Execution"),
        ],
        "Pipeline Evaluation": [
            st.Page("pages/create_dataset.py", title="📝 Create Ground Truth"),
            st.Page("pages/run_predictions.py", title="🔄 Create New Predictions"),
            st.Page("pages/evaluate_metrics.py", title="🎯 Evaluate Predictions Metrics"),
            st.Page("pages/compute_metrics.py", title="📈 Compute Metrics (remove)"),
            st.Page("pages/list_experiments.py", title="📚 List Previous Evaluations"),
        ]
    }
    
    pg = st.navigation(pages)
    pg.run()
    
if __name__ == "__main__":
    main()