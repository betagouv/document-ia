"""Dashboard page with interactive visualizations."""

import streamlit as st

from document_ia_evals.utils.config import config

# Page configuration
st.set_page_config(
    page_title=f"Home | {config.APP_TITLE}",
    page_icon="📊",
    layout=config.LAYOUT  # pyright: ignore [reportArgumentType]
)


def main():
    """Main dashboard page function."""
    # Main content
    st.title("🏠 Welcome to Document IA Evals")

    st.markdown("""
    ### Main features
    - Execute a workflow on a document
    - Retrieve results of an execution
    - Create ground truth
    - Create new predictions

    ### Quick Start

    ```bash
    # Install dependencies
    poetry install

    # Run the application
    poetry run streamlit run src/document_ia_evals/app.py
    ```
    """)

    if config.ALLOW_INSECURE_REQUESTS is True:
        st.info(
            f"⚠️ ALLOW_INSECURE_REQUESTS is {config.ALLOW_INSECURE_REQUESTS}. It is used to bypass ssl certificate verification when using LabelStudio behind a VPN.")


if __name__ == "__main__":
    main()
