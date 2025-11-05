"""Main Streamlit application entry point."""

import streamlit as st

from src.components.sidebar import render_sidebar
from src.utils.config import Config

# Initialize configuration
Config.ensure_directories()

# Page configuration
st.set_page_config(
    page_title=Config.APP_TITLE,
    page_icon=Config.PAGE_ICON,
    layout=Config.LAYOUT,
    initial_sidebar_state="expanded"
)


def main():
    """Main application function."""
    # Render sidebar
    sidebar_settings = render_sidebar()
    
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
    poetry run streamlit run app.py
    ```
    """)
    
if __name__ == "__main__":
    main()