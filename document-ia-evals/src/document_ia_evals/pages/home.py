"""Dashboard page with interactive visualizations."""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from document_ia_evals.utils.config import config

# Page configuration
st.set_page_config(
    page_title=f"Dashboard | {config.APP_TITLE}",
    page_icon="📊",
    layout=config.LAYOUT
)


def generate_sample_data():
    """Generate sample data for demonstration."""
    dates = pd.date_range(
        start=datetime.now() - timedelta(days=30),
        end=datetime.now(),
        freq='D'
    )
    
    df = pd.DataFrame({
        'date': dates,
        'sales': np.random.randint(100, 500, len(dates)),
        'visitors': np.random.randint(1000, 5000, len(dates)),
        'conversion_rate': np.random.uniform(2, 8, len(dates))
    })
    
    return df


def main():
    """Main dashboard page function."""
    # Main content
    st.title("🏠 Welcome to Document IA Evals")
    
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

    if config.ALLOW_INSECURE_REQUESTS is True:
        st.info(f"⚠️ ALLOW_INSECURE_REQUESTS is {config.ALLOW_INSECURE_REQUESTS}. It is used to bypass ssl certificate verification when using LabelStudio behind a VPN.")


if __name__ == "__main__":
    main()