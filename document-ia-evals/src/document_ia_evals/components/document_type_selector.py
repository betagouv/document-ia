"""Document type selector smart component."""

import streamlit as st

from document_ia_schemas import SupportedDocumentType


def render_document_type_selector(
    label: str = "Type de document",
    help_text: str | None = None,
    default_index: int = 0,
) -> SupportedDocumentType:
    """
    Render document type selection component.
    
    This is a smart component that displays all available document types
    from the SupportedDocumentType enum.
    
    Args:
        label: Label for the selectbox
        help_text: Optional help text to display
        default_index: Default selected index (0-based)
    
    Returns:
        Selected SupportedDocumentType
    """
    doc_type_options = list(SupportedDocumentType)
    
    selected_doc_type: SupportedDocumentType = st.selectbox(
        label,
        options=doc_type_options,
        format_func=lambda x: x.name.replace("_", " ").title(),
        index=default_index,
        help=help_text,
    )
    
    return selected_doc_type

