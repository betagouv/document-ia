"""Review field-level prediction errors for one Label Studio model."""

from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from document_ia_evals.components import (
    ClientType,
    render_document_type_selector,
    render_project_selector,
)
from document_ia_evals.services.prediction_error_review_service import (
    ErrorReviewDocument,
    find_error_documents,
    get_field_metric_options,
    get_model_versions,
)
from document_ia_evals.services.create_predictions_service import (
    extract_s3_url_from_task_url,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import (
    extract_project_metadata,
    fetch_project_tasks,
)
from document_ia_evals.utils.s3 import download_from_s3
from document_ia_schemas import SupportedDocumentType


@st.cache_data(ttl=300)
def load_project_tasks(project_id: int) -> list[dict[str, Any]]:
    """Load all project tasks, including predictions and annotations."""
    return fetch_project_tasks(project_id)


@st.cache_data(ttl=300)
def load_pdf_bytes(document_url: str) -> bytes:
    """Download a PDF for embedding in Streamlit's in-browser viewer."""
    source_url = extract_s3_url_from_task_url(document_url)
    if source_url.startswith("s3://"):
        file_content, _ = download_from_s3(source_url)
        if not file_content.startswith(b"%PDF"):
            raise ValueError("La source S3 ne renvoie pas un fichier PDF valide.")
        return file_content

    response = requests.get(
        source_url,
        timeout=60,
        verify=not config.ALLOW_INSECURE_REQUESTS,
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError("L’URL ne renvoie pas un fichier PDF valide.")
    return response.content


@st.cache_data(ttl=300)
def save_pdf_locally(document_url: str) -> str:
    """Save the PDF in the app static directory and return its HTTP URL."""
    pdf_directory = Path(__file__).resolve().parent.parent / "static" / "review-pdfs"
    pdf_directory.mkdir(parents=True, exist_ok=True)
    filename = f"{sha256(document_url.encode('utf-8')).hexdigest()}.pdf"
    pdf_path = pdf_directory / filename
    if not pdf_path.exists():
        pdf_path.write_bytes(load_pdf_bytes(document_url))
    return f"/app/static/review-pdfs/{filename}"


def render_browser_pdf(document_url: str, height: int = 850) -> None:
    """Render a PDF through the browser's built-in PDF viewer."""
    pdf_url = escape(save_pdf_locally(document_url), quote=True)
    pdf_display = (
        f'<embed src="{pdf_url}" type="application/pdf" '
        f'style="width: 100%; height: {height}px; border: none;">'
    )
    st.markdown(pdf_display, unsafe_allow_html=True)


def _change_selected_document(delta: int, document_count: int) -> None:
    """Move the selected document by one position."""
    current_index = st.session_state.get("review_document_index", 0)
    st.session_state["review_document_index"] = min(
        max(current_index + delta, 0), document_count - 1
    )


def _render_document(document: ErrorReviewDocument) -> None:
    """Render the selected document on the left side of the review."""
    if not document.document_url:
        st.warning("Aucune URL de document n’est disponible pour cette tâche.")
        return

    if any(extension in document.document_url.lower() for extension in (".png", ".jpg", ".jpeg", ".webp")):
        st.image(document.document_url, use_container_width=True)
    else:
        try:
            render_browser_pdf(document.document_url)
        except Exception as exc:
            st.error(f"Impossible d’afficher le PDF dans le navigateur : {exc}")


def _render_errors(document: ErrorReviewDocument) -> None:
    """Render the selected document's field-level errors."""
    st.subheader("Champs erronés")
    for error in document.errors:
        with st.container(border=True):
            st.markdown(f"**{error.field}** · `{error.metric}`")
            st.markdown(f"Prédit : `{error.predicted}`")
            st.markdown(f"Attendu : `{error.expected}`")


def main() -> None:
    title = "🔎 Revue des erreurs de prédiction"
    st.set_page_config(page_title=title, page_icon="🔎", layout="wide")
    st.title(title)
    st.caption(f"Label Studio : {config.LABEL_STUDIO_URL}")

    project = render_project_selector(
        client_type=ClientType.LEGACY,
        label="Sélectionnez un projet Label Studio",
        show_details=True,
        show_task_count=True,
        required=False,
    )
    if not project:
        st.info("Sélectionnez un projet pour commencer.")
        return

    try:
        tasks = load_project_tasks(project.project_id)
    except Exception as exc:
        st.error(f"Impossible de charger les tâches Label Studio : {exc}")
        return

    metadata = extract_project_metadata(project.project_description) or {}
    suggested_document_type = metadata.get("document_type")
    if suggested_document_type:
        try:
            suggested_document_type = SupportedDocumentType.from_str(suggested_document_type).value
        except ValueError:
            suggested_document_type = None

    document_type_key = f"review_document_type_{project.project_id}"
    if suggested_document_type and document_type_key not in st.session_state:
        st.session_state[document_type_key] = next(
            item
            for item in SupportedDocumentType
            if item.value == suggested_document_type
        )

    selected_doc_type = render_document_type_selector(
        label="Type de document",
        help_text="Le schéma détermine les champs et métriques disponibles.",
        optional=False,
        key=document_type_key,
    )
    if selected_doc_type is None:
        return
    document_type = selected_doc_type.value

    if suggested_document_type and suggested_document_type != document_type:
        st.info(f"Le projet suggère le type `{suggested_document_type}`.")

    model_versions = get_model_versions(tasks)
    if not model_versions:
        st.warning("Aucune prédiction avec un model_version n’a été trouvée dans ce projet.")
        return
    model_version = st.selectbox(
        "Modèle à examiner",
        model_versions,
        key=f"review_model_{project.project_id}",
    )

    try:
        options = get_field_metric_options(document_type)
    except (ValueError, ImportError) as exc:
        st.error(f"Impossible de charger le schéma du document : {exc}")
        return
    option_keys = [(option.field, option.metric) for option in options]
    option_labels = {key: f"{key[0]} × {key[1]}" for key in option_keys}
    selected_keys = st.multiselect(
        "Couples Field × Metric à contrôler",
        options=option_keys,
        default=option_keys,
        format_func=lambda key: option_labels[key],
        key=f"review_pairs_{project.project_id}_{document_type}",
    )

    if not selected_keys:
        st.warning("Sélectionnez au moins un couple Field × Metric.")
        return

    if st.button("Analyser les erreurs", type="primary"):
        with st.spinner("Comparaison des prédictions avec les Ground Truth…"):
            documents, ambiguous_task_ids = find_error_documents(
                tasks=tasks,
                model_version=model_version,
                document_type=document_type,
                selected_pairs=set(selected_keys),
            )
        st.session_state["review_error_documents"] = documents
        st.session_state["review_error_config"] = (
            project.project_id,
            model_version,
            document_type,
            tuple(sorted(selected_keys)),
        )
        st.session_state["review_ambiguous_tasks"] = ambiguous_task_ids

    current_config = (
        project.project_id,
        model_version,
        document_type,
        tuple(sorted(selected_keys)),
    )
    if st.session_state.get("review_error_config") != current_config:
        st.info("Cliquez sur « Analyser les erreurs » pour appliquer cette configuration.")
        return

    ambiguous_task_ids = st.session_state.get("review_ambiguous_tasks", [])
    if ambiguous_task_ids:
        st.warning(f"{len(ambiguous_task_ids)} tâche(s) exclue(s) : plusieurs prédictions portent ce model_version.")

    documents: list[ErrorReviewDocument] = sorted(
        st.session_state.get("review_error_documents", []),
        key=lambda document: (
            0,
            int(document.task_id),
        )
        if str(document.task_id).isdigit()
        else (1, str(document.task_id)),
    )
    st.metric("Documents erronés", len(documents))
    if not documents:
        st.success("Aucune erreur trouvée pour les couples sélectionnés.")
        return

    labels = {
        index: f"Tâche {document.task_id} · {len(document.errors)} erreur(s)"
        for index, document in enumerate(documents)
    }
    selected_index = st.session_state.get("review_document_index", 0)
    selected_index = min(max(selected_index, 0), len(documents) - 1)
    st.session_state["review_document_index"] = selected_index

    previous, selector, following = st.columns([1, 4, 1])
    with previous:
        st.button(
            "← Précédent",
            disabled=selected_index == 0,
            on_click=_change_selected_document,
            args=(-1, len(documents)),
            use_container_width=True,
        )
    with selector:
        selected_index = st.selectbox(
            "Document erroné",
            options=list(labels),
            format_func=lambda index: labels[index],
            key="review_document_index",
        )
    with following:
        st.button(
            "Suivant →",
            disabled=selected_index == len(documents) - 1,
            on_click=_change_selected_document,
            args=(1, len(documents)),
            use_container_width=True,
        )
    document = documents[selected_index]
    st.caption(f"Document {selected_index + 1} / {len(documents)} · Task ID: {document.task_id} · Prediction ID: {document.prediction_id}")

    left, right = st.columns([3, 2])
    with left:
        _render_document(document)
    with right:
        _render_errors(document)


if __name__ == "__main__":
    main()
