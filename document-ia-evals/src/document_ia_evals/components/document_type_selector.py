"""Document type selector smart component."""

import json
from typing import overload, Literal

import streamlit as st

from document_ia_schemas import SupportedDocumentType


@overload
def render_document_type_selector(
    label: str = "Type de document",
    help_text: str | None = None,
    default_index: int = 0,
    optional: Literal[False] = False,
    checkbox_label: str = "Outrepasser l'étape de classification",
    checkbox_help: str | None = None,
) -> SupportedDocumentType: ...


@overload
def render_document_type_selector(
    label: str = "Type de document",
    help_text: str | None = None,
    default_index: int = 0,
    optional: Literal[True] = True,
    checkbox_label: str = "Outrepasser l'étape de classification",
    checkbox_help: str | None = None,
) -> SupportedDocumentType | None: ...


def render_document_type_selector(
    label: str = "Type de document",
    help_text: str | None = None,
    default_index: int = 0,
    optional: bool = True,
    checkbox_label: str = "Outrepasser l'étape de classification",
    checkbox_help: str | None = None,
) -> SupportedDocumentType | None:
    """
    Render document type selection component with optional checkbox.
    
    This is a smart component that displays all available document types
    from the SupportedDocumentType enum, with an optional checkbox to enable/disable
    the document type override.
    
    Args:
        label: Label for the selectbox
        help_text: Optional help text to display
        default_index: Default selected index (0-based)
        optional: Whether to show a checkbox to enable/disable document type selection
        checkbox_label: Label for the checkbox
        checkbox_help: Optional help text for the checkbox
    
    Returns:
        Selected SupportedDocumentType if checkbox is checked (or if optional=False), 
        None otherwise
    """
    # Wrap in a container for visual grouping
    with st.container(border=True):
        # Show checkbox to enable/disable document type override
        override_classification = True
        if optional:
            override_classification = st.checkbox(
                checkbox_label,
                value=False,
                help=checkbox_help or "Cochez cette case pour spécifier manuellement le type de document et outrepasser la classification automatique",
            )
        
        # Only show document type selector if checkbox is checked
        if not override_classification:
            return None
        
        doc_type_options = list(SupportedDocumentType)
        
        selected_doc_type: SupportedDocumentType = st.selectbox(
            label,
            options=doc_type_options,
            format_func=lambda x: x.name.replace("_", " ").title(),
            index=default_index,
            help=help_text,
        )
        
        # Show extraction parameters info inline
        extraction_params_preview = {"document-type": selected_doc_type.value}
        st.info(f"ℹ️ Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")
        
        return selected_doc_type