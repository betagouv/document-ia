"""Prompt Playground page.

This page provides:
1. Batch workflow execution on a Label Studio dataset
2. Disk-backed tracking of execution_id per Label Studio file/task
3. Replay UI to inspect dumped prompts and re-run LLM prediction
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import streamlit as st
from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError
from label_studio_sdk import LseTask
from document_ia_infra.openai.response_format import get_response_format
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema

from document_ia_evals.components import (
    ClientType,
    get_client,
    render_document_type_selector,
    render_project_selector,
    render_workflow_selector,
)
from document_ia_evals.services.create_predictions_service import (
    get_failed_tasks,
    get_processing_statistics,
    run_workflow_on_dataset,
)
from document_ia_evals.utils.config import config
from document_ia_evals.utils.label_studio import annotation_results_to_dict


def render_configuration_warnings() -> bool:
    """
    Check and display warnings for missing configuration.

    Returns:
        True if all configuration is valid, False otherwise
    """
    if not config.DOCUMENT_IA_API_KEY:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return False

    s3_vars = {
        "S3_ENDPOINT": config.S3_ENDPOINT,
        "S3_ACCESS_KEY": config.S3_ACCESS_KEY,
        "S3_SECRET_KEY": config.S3_SECRET_KEY,
        "S3_BUCKET_NAME": config.S3_BUCKET_NAME,
        "S3_REGION": config.S3_REGION,
    }
    missing_s3 = [var for var, val in s3_vars.items() if not val]
    if missing_s3:
        st.warning(f"⚠️ Missing S3 configuration: {', '.join(missing_s3)}")
        return False

    openai_base_url = os.getenv("OPENAI_BASE_URL")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_base_url or not openai_api_key:
        st.warning(
            "OPENAI_BASE_URL et OPENAI_API_KEY sont requis pour rejouer la prédiction LLM."
        )
        return False

    return True


def render_worker_config() -> int:
    return st.number_input(
        "Nombre de tâches à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )


def render_model_version_input(default_value: str) -> str:
    return st.text_input(
        "Nom de l'annotation (model version)",
        value=default_value,
        help="Nom affiché pour cette annotation dans Label Studio. Par défaut: ID du workflow",
    )


OPENAI_REPLAY_DIR = Path("/tmp/document-ia-openai-replay")
PERSISTENCE_DIR = config.DATA_DIR / "prompt_improvement"
PERSISTENCE_FILE = PERSISTENCE_DIR / "execution_mappings.json"
SYSTEM_PROMPT_HISTORY_DIR = PERSISTENCE_DIR / "system_prompt"


class ReplayPayload(BaseModel):
    execution_id: str
    document_type: str | None = None
    model: str | None = None
    system_prompt: str
    user_prompt: str


def _build_response_format_from_document_type(
    document_type: str | None,
) -> dict[str, Any] | None:
    if not document_type:
        return None

    try:
        supported_document_type = SupportedDocumentType.from_str(document_type)
        schema_instance = resolve_extract_schema(supported_document_type.value)
        extract_class = schema_instance.document_model
        response_model = get_response_format(extract_class)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "schema": response_model.model_json_schema(),
            },
        }
    except Exception:
        return None


def _default_state() -> dict[str, Any]:
    return {
        "latest_by_task": {},
        "history": [],
        "system_prompt_by_document_type": {},
    }


def _load_persisted_state() -> dict[str, Any]:
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    if not PERSISTENCE_FILE.exists():
        return _default_state()

    try:
        state = json.loads(PERSISTENCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()

    if not isinstance(state, dict):
        return _default_state()
    if "latest_by_task" not in state or not isinstance(state["latest_by_task"], dict):
        state["latest_by_task"] = {}
    if "history" not in state or not isinstance(state["history"], list):
        state["history"] = []
    if "system_prompt_by_document_type" not in state or not isinstance(
        state["system_prompt_by_document_type"], dict
    ):
        state["system_prompt_by_document_type"] = {}
    return state


def _save_persisted_state(state: dict[str, Any]) -> None:
    PERSISTENCE_DIR.mkdir(parents=True, exist_ok=True)
    PERSISTENCE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _extract_filename_from_task_url(url: str | None) -> str:
    if not url:
        return "unknown"
    cleaned = url.split("?")[0].rstrip("/")
    if "/" not in cleaned:
        return cleaned or "unknown"
    return cleaned.rsplit("/", 1)[-1] or "unknown"


def _normalize_document_type(document_type: str | None) -> str:
    normalized = (document_type or "").strip()
    return normalized if normalized else "unknown"


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)


def _persist_system_prompt_snapshot(
    *,
    document_type: str,
    system_prompt: str,
    reason: str,
    task_id: int | None = None,
    execution_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    doc_type_key = _safe_path_component(_normalize_document_type(document_type))
    out_dir = SYSTEM_PROMPT_HISTORY_DIR / doc_type_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{timestamp}.json"

    payload = {
        "timestamp": now.isoformat(),
        "document_type": _normalize_document_type(document_type),
        "reason": reason,
        "task_id": task_id,
        "execution_id": execution_id,
        "system_prompt": system_prompt,
    }
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _set_system_prompt_for_document_type(
    *,
    state: dict[str, Any],
    document_type: str,
    system_prompt: str,
    reason: str,
    task_id: int | None = None,
    execution_id: str | None = None,
) -> bool:
    normalized_doc_type = _normalize_document_type(document_type)
    prompts_by_doc_type: dict[str, str] = state["system_prompt_by_document_type"]
    current_prompt = prompts_by_doc_type.get(normalized_doc_type)

    if current_prompt == system_prompt:
        return False

    prompts_by_doc_type[normalized_doc_type] = system_prompt
    _save_persisted_state(state)
    _persist_system_prompt_snapshot(
        document_type=normalized_doc_type,
        system_prompt=system_prompt,
        reason=reason,
        task_id=task_id,
        execution_id=execution_id,
    )
    return True


def _extract_ground_truth(task: LseTask) -> dict[str, Any] | None:
    if not task.annotations:
        return None

    selected_result = None
    for annotation in task.annotations:
        ground_truth = annotation.get("ground_truth", False)
        result = annotation.get("result", None) or []
        if ground_truth and result:
            selected_result = result
            break

    if not selected_result:
        return None

    data, _ = annotation_results_to_dict(selected_result)
    return data


def _load_replay_payload(execution_id: str) -> ReplayPayload | None:
    replay_path = OPENAI_REPLAY_DIR / f"{execution_id}.json"
    if not replay_path.exists():
        return None
    try:
        return ReplayPayload.model_validate_json(replay_path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError):
        return None


def _call_openai_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any] | None = None,
) -> ChatCompletion:
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=120,
    )

    data: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    if response_format is not None:
        data["response_format"] = response_format

    return client.chat.completions.create(**data)


def _store_execution_mapping(
    *,
    state: dict[str, Any],
    processing_results: dict[int, dict[str, Any]],
    tasks_by_id: dict[int, LseTask],
    workflow_id: str,
    project_id: int,
    project_title: str,
    model_version: str,
    selected_doc_type: Any,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    latest_by_task: dict[str, Any] = state["latest_by_task"]

    for task_id, result in processing_results.items():
        execution_id = result.get("execution_id")
        if not execution_id:
            continue

        task = tasks_by_id.get(task_id)
        task_url = None
        if task is not None:
            task_data = getattr(task, "data", None) or {}
            task_url = task_data.get("pdf")

        latest_by_task[str(task_id)] = {
            "task_id": task_id,
            "label_studio_file_ref": task_url,
            "filename": _extract_filename_from_task_url(task_url),
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "project_id": project_id,
            "project_title": project_title,
            "model_version": model_version,
            "document_type": selected_doc_type.value if selected_doc_type else None,
            "updated_at": now_iso,
        }

    state["history"].append(
        {
            "timestamp": now_iso,
            "workflow_id": workflow_id,
            "project_id": project_id,
            "project_title": project_title,
            "results": processing_results,
        }
    )


def _render_processing_results(results: dict[int, dict[str, Any]]) -> None:
    success_count, total_count = get_processing_statistics(results)
    st.success(f"✅ {success_count}/{total_count} tâches traitées avec succès")

    if success_count < total_count:
        st.warning("⚠️ Certaines tâches n'ont pas pu être traitées:")
        failed_tasks = get_failed_tasks(results)
        for task_id, error, execution_id, processing_time_ms in failed_tasks:
            st.error(f"- Task {task_id}: {error}")
            if execution_id:
                st.info(
                    f"  Execution ID: `{execution_id}`\n"
                    f"  Processing Time: `{processing_time_ms}`"
                )


@st.fragment
def _render_latest_inference_section(
    *,
    state: dict[str, Any],
    tasks_by_id: dict[int, LseTask],
    project_id: int,
) -> None:
    st.subheader("Résultat par fichier / task Label Studio")
    latest_by_task: dict[str, Any] = state["latest_by_task"]

    entries = [
        entry
        for entry in latest_by_task.values()
        if entry.get("project_id") == project_id
    ]

    if not entries:
        st.info(
            "Aucune inférence persistée pour ce dataset. "
            "Lancez d'abord une exécution."
        )
        return

    entries.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    options = {
        str(e["task_id"]): (
            f"Task {e['task_id']} - {e.get('filename', 'unknown')} "
            f"(exec: {e['execution_id']}...)"
        )
        for e in entries
    }

    selected_task_id = st.selectbox(
        "Fichier / task Label Studio",
        options=list(options.keys()),
        format_func=lambda x: options[x],
    )

    selected = latest_by_task[selected_task_id]

    replay_payload = _load_replay_payload(selected["execution_id"])
    if replay_payload is None:
        st.warning(
            "Replay introuvable sur ce host pour cette exécution. "
            f"Fichier attendu: `{OPENAI_REPLAY_DIR / (selected['execution_id'] + '.json')}`"
        )
        return

    st.write("**Référence Label Studio**")
    document_type = _normalize_document_type(
        replay_payload.document_type or selected.get("document_type")
    )
    st.json(
        {
            "task_id": selected["task_id"],
            "label_studio_file_ref": selected.get("label_studio_file_ref"),
            "execution_id": selected["execution_id"],
            "workflow_id": selected.get("workflow_id"),
            "model_version": selected.get("model_version"),
            "document_type": document_type,
            "updated_at": selected.get("updated_at"),
        }
    )

    prompts_by_doc_type: dict[str, str] = state["system_prompt_by_document_type"]
    if document_type not in prompts_by_doc_type:
        _set_system_prompt_for_document_type(
            state=state,
            document_type=document_type,
            system_prompt=replay_payload.system_prompt,
            reason="replay_payload_init",
            task_id=selected.get("task_id"),
            execution_id=selected.get("execution_id"),
        )
    current_system_prompt = prompts_by_doc_type.get(document_type, replay_payload.system_prompt)

    st.write("**System Prompt**")
    system_prompt_tabs = st.tabs(["Editer", "Preview"])
    edited_system_prompt = ""
    with system_prompt_tabs[0]:
        edited_system_prompt = st.text_area(
            "System Prompt",
            value=current_system_prompt,
            height="content",
            key=f"system_prompt_editor::{document_type}",
        )
        if edited_system_prompt != current_system_prompt:
            _set_system_prompt_for_document_type(
                state=state,
                document_type=document_type,
                system_prompt=edited_system_prompt,
                reason="manual_edit",
                task_id=selected.get("task_id"),
                execution_id=selected.get("execution_id"),
            )
    with system_prompt_tabs[1]:
        st.markdown(edited_system_prompt)

    st.write("**User Prompt**")
    st.code(replay_payload.user_prompt, language="markdown")

    task = tasks_by_id.get(selected["task_id"])
    ground_truth = _extract_ground_truth(task) if task is not None else None

    model = replay_payload.model or selected.get("model_version")
    if not model:
        st.warning("Modèle introuvable dans le replay.")
        return

    prediction_button = st.button(f"Faire la prédiction avec le LLM {model}", type="primary")
    use_edited_system_prompt = st.checkbox("Utiliser le system prompt édité", value=True)
    col1, col2 = st.columns(2)

    with col1:
        st.write("**Ground truth associée**")
        if ground_truth is None:
            st.warning("Aucune annotation de ground truth trouvée pour cette task.")
        else:
            st.json(ground_truth)

    with col2:
        if prediction_button:
            response_format = (
                _build_response_format_from_document_type(replay_payload.document_type)
                or {"type": "json_object"}
            )

            with st.spinner("Appel LLM en cours...", show_time=True):
                openai_base_url = os.environ["OPENAI_BASE_URL"]
                openai_api_key = os.environ["OPENAI_API_KEY"]
                try:
                    llm_response = _call_openai_chat_completion(
                        base_url=openai_base_url,
                        api_key=openai_api_key,
                        model=model,
                        system_prompt=edited_system_prompt if use_edited_system_prompt else replay_payload.system_prompt,
                        user_prompt=replay_payload.user_prompt,
                        response_format=response_format,
                    )
                except Exception as e:
                    st.error(f"Erreur lors de l'appel LLM: {e}")
                    return

            content = llm_response.choices[0].message.content

            if content:
                try:
                    st.write("**Prédiction**")
                    st.json(json.loads(content))
                except Exception:
                    st.warning("Réponse du LLM non parsable en JSON:")
                    st.code(content)
                    pass


def main() -> None:
    title = "Amélioration du prompt d'extraction de données pour un type de document"
    st.set_page_config(page_title=title, page_icon="🔄")
    st.title(title)
    st.caption(
        f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, "
        f"S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )

    st.caption(f"Persistance locale: {PERSISTENCE_FILE}")

    st.markdown(
        """
    Cette page vous permet d'améliorer le prompt d'extraction de données pour un type de document spécifique :
    1. Sélection du workflow à exécuter
    2. Sélection du dataset Label Studio
    3. Exécution du workflow sur chaque fichier
    4. Récupération des vérités de terrain et des prédictions
    5. Analyse des erreurs pour identifier les points d'amélioration du prompt avec un LLM
    """
    )

    if not render_configuration_warnings():
        return

    api_key = config.DOCUMENT_IA_API_KEY

    workflow_selection = render_workflow_selector()
    if workflow_selection is None:
        return

    selected_doc_type = render_document_type_selector()

    project_selection = render_project_selector(
        client_type=ClientType.SDK,
        label="Sélectionnez un dataset Label Studio",
        show_details=True,
        show_task_count=True,
    )
    if project_selection is None:
        return

    ls_client = get_client(ClientType.SDK)

    n_workers = render_worker_config()
    model_version = render_model_version_input(workflow_selection.workflow_id)

    tasks: list[LseTask] = [
        task
        for task in ls_client.tasks.list(project=project_selection.project_id, fields="all")
    ]
    tasks_by_id = {task.id: task for task in tasks}
    state = _load_persisted_state()

    if st.button("Lancer l'exécution du workflow", type="primary"):
        extraction_parameters = None
        if selected_doc_type:
            extraction_parameters = {"document-type": selected_doc_type.value}

        st.info(
            f"🚀 Exécution du workflow '{workflow_selection.workflow_id}' "
            f"sur le dataset '{project_selection.project_title}'..."
        )

        with st.spinner("Processing tasks...", show_time=True):
            pbar = st.progress(0, text="Executing workflows...")

            def update_progress(current: int, total: int) -> None:
                pbar.progress(current / total)

            processing_results = run_workflow_on_dataset(
                workflow_id=workflow_selection.workflow_id,
                project_id=project_selection.project_id,
                api_key=api_key,
                ls_client=ls_client,
                n_workers=n_workers,
                model_version=model_version if model_version else None,
                extraction_parameters=extraction_parameters,
                on_progress=update_progress,
            )

        if not processing_results:
            st.warning("No tasks found in the selected dataset.")
        else:
            _render_processing_results(processing_results)
            _store_execution_mapping(
                state=state,
                processing_results=processing_results,
                tasks_by_id=tasks_by_id,
                workflow_id=workflow_selection.workflow_id,
                project_id=project_selection.project_id,
                project_title=project_selection.project_title,
                model_version=model_version,
                selected_doc_type=selected_doc_type,
            )
            _save_persisted_state(state)

            with st.expander("Détails des résultats"):
                st.json(processing_results)

    st.divider()
    _render_latest_inference_section(
        state=state,
        tasks_by_id=tasks_by_id,
        project_id=project_selection.project_id,
    )


if __name__ == "__main__":
    main()
