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
    
    # Main content
    st.title("🏠 Welcome to Streamlit App")
    
    st.markdown("""
    ### Navigation
    
    Use the sidebar to navigate between different pages:
    - **Home** - This page
    - **Dashboard** - [WIP] Interactive dashboard with charts
    - **New Experiment** - Page to create a new Evaluation experiment
    - **Experiment Results** - Page to show an experiment result
    
    ### Quick Start
    
    ```bash
    # Install dependencies
    poetry install
    
    # Run the application
    poetry run streamlit run src/document_ia_evals/app.py
    ```
    """)
    
if __name__ == "__main__":
    main()