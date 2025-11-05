"""Sidebar component with navigation and settings."""

import streamlit as st


def render_sidebar():
    """Render the sidebar with navigation and settings."""
    with st.sidebar:
        
        st.subheader("Settings")
        theme = st.selectbox(
            "Theme",
            ["Light", "Dark", "Auto"],
            index=0
        )
        
        st.markdown("---")
        
        st.subheader("About")
        st.info(
            "This is a Streamlit application with a clean, "
            "modular code structure."
        )
        
        return {"theme": theme}