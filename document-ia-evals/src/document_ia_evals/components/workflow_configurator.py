from typing import Any, Dict, Tuple
from document_ia_evals.utils.config import config
from document_ia_streamlit_common.components import (
    render_workflow_configurator as common_render_workflow_configurator,
)


def render_workflow_configurator(
    api_key: str,
    key_suffix: str = "",
    default_workflow_id: str | None = None,
    default_document_type: str | None = None,
    base_url: str | None = None,
) -> Tuple[Dict[str, Any] | None, Dict[str, Any]]:
    """Renders the workflow configuration component delegating to document-ia-streamlit-common."""
    target_base_url = base_url or config.DOCUMENT_IA_BASE_URL
    return common_render_workflow_configurator(
        base_url=target_base_url,
        api_key=api_key,
        key_suffix=key_suffix,
        default_workflow_id=default_workflow_id,
        default_document_type=default_document_type,
    )
