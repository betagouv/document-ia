"""Prompt Playground page.

This page provides:
1. Batch workflow execution on a Label Studio dataset
2. Disk-backed tracking of execution_id per Label Studio file/task
3. Replay UI to inspect dumped prompts and re-run LLM prediction
"""

import json
import os
from datetime import datetime, timezone
from typing import Any
import streamlit as st
from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel
from label_studio_sdk import LseTask
from document_ia_infra.openai.response_format import get_response_format
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema

from document_ia_evals.components import (
    ClientType,
    get_client,
    render_project_selector,
    render_workflow_configurator,
)
from document_ia_evals.services.create_predictions_service import (
    get_failed_tasks,
    get_processing_statistics,
    run_workflow_on_dataset_v2,
)
from document_ia_evals.pages.review_prediction_errors import render_browser_pdf
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
    """Load playground state from the current Streamlit session only."""
    state = st.session_state.get("prompt_playground_state")
    if not isinstance(state, dict):
        state = _default_state()
    if "latest_by_task" not in state or not isinstance(state["latest_by_task"], dict):
        state["latest_by_task"] = {}
    if "history" not in state or not isinstance(state["history"], list):
        state["history"] = []
    if "system_prompt_by_document_type" not in state or not isinstance(
        state["system_prompt_by_document_type"], dict
    ):
        state["system_prompt_by_document_type"] = {}
    st.session_state["prompt_playground_state"] = state
    return state


def _save_persisted_state(state: dict[str, Any]) -> None:
    """Save playground state in the current Streamlit session only."""
    st.session_state["prompt_playground_state"] = state


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


def _replay_payload_from_execution(
    execution_id: str, execution_result: dict[str, Any] | None
) -> ReplayPayload | None:
    """Build a replay payload from API metadata when worker /tmp is not shared."""
    for metadata in (execution_result or {}).get("workflow_metadata") or []:
        if not metadata.get("system_prompt") or metadata.get("user_prompt") is None:
            continue
        return ReplayPayload(
            execution_id=execution_id,
            document_type=None,
            model=metadata.get("model"),
            system_prompt=metadata["system_prompt"],
            user_prompt=metadata["user_prompt"],
        )
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
            "execution_result": result.get("execution_result"),
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


def _render_extraction_comparison(
    prediction: dict[str, Any] | None, ground_truth: dict[str, Any] | None
) -> None:
    """Show extracted properties next to the annotation used as reference."""
    st.write("**Comparaison avec la ground truth**")
    if ground_truth is None:
        st.warning("Aucune annotation de ground truth trouvée pour cette tâche.")
        if prediction is not None:
            st.json(prediction)
        return

    raw_prediction = prediction or {}
    if "extraction" in raw_prediction:
        predicted_properties = raw_prediction["extraction"].get("properties", [])
        predicted = {
            item.get("name"): item.get("value")
            for item in predicted_properties
            if item.get("name")
        }
    elif isinstance(raw_prediction.get("properties"), dict):
        predicted = raw_prediction["properties"]
    elif isinstance(raw_prediction.get("properties"), list):
        predicted = {
            item.get("name"): item.get("value")
            for item in raw_prediction["properties"]
            if item.get("name")
        }
    else:
        predicted = raw_prediction
    expected = ground_truth.get("properties", ground_truth)
    fields = sorted(set(predicted) | set(expected))
    if not fields:
        st.info("Aucun champ à comparer.")
        return
    rows = []
    for field in fields:
        value = predicted.get(field)
        expected_value = expected.get(field)
        rows.append(
            {
                "Champ": field,
                "Prédit": value,
                "Ground truth": expected_value,
                "Statut": "✅" if value == expected_value else "❌",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_yoloworld_output(execution_result: dict[str, Any]) -> None:
    """Display YoloWorld previews returned in v2 debug metadata."""
    images: list[str] = []
    for metadata in execution_result.get("workflow_metadata") or []:
        if metadata.get("step_name") != "PreprocessFileStep":
            continue
        images.extend(metadata.get("output_images") or [])

    if not images:
        return

    st.write("**Sortie YoloWorld**")
    st.caption("Images après recadrage par l'étape de preprocessing YoloWorld")
    columns = st.columns(min(len(images), 3))
    for index, image in enumerate(images):
        with columns[index % len(columns)]:
            st.image(image, caption=f"Page {index + 1}", use_container_width=True)


@st.fragment
def _render_latest_inference_section(
    *,
    state: dict[str, Any],
    tasks_by_id: dict[int, LseTask],
    project_id: int,
    task_id: int,
) -> None:
    latest_by_task: dict[str, Any] = state["latest_by_task"]
    selected = latest_by_task.get(str(task_id))
    if selected is None or selected.get("project_id") != project_id:
        st.info(
            "Aucune inférence persistée pour cette task. Lancez d'abord une exécution."
        )
        return

    replay_payload = _replay_payload_from_execution(
        selected["execution_id"], selected.get("execution_result")
    )
    if replay_payload is None:
        st.info("Les prompts ne sont pas disponibles pour cette exécution.")
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

    task = tasks_by_id.get(selected["task_id"])
    ground_truth = _extract_ground_truth(task) if task is not None else None

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
    current_system_prompt = prompts_by_doc_type.get(
        document_type, replay_payload.system_prompt
    )

    st.write("**User Prompt**")
    st.caption("Texte transmis à l’étape d’extraction après l’OCR")
    st.text_area(
        "Texte OCR",
        value=replay_payload.user_prompt,
        height=260,
        disabled=True,
        key=f"ocr_text::{task_id}::{selected['execution_id']}",
    )

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

    execution_result = selected.get("execution_result")
    if execution_result:
        _render_yoloworld_output(execution_result)
        _render_extraction_comparison(execution_result, ground_truth)

    model = replay_payload.model or selected.get("model_version")
    if not model:
        st.warning("Modèle introuvable dans le replay.")
        return

    prediction_button = st.button(
        f"Faire la prédiction avec le LLM {model}", type="primary"
    )
    use_edited_system_prompt = st.checkbox(
        "Utiliser le system prompt édité", value=True
    )
    if prediction_button:
            response_format = _build_response_format_from_document_type(
                replay_payload.document_type
            ) or {"type": "json_object"}

            with st.spinner("Appel LLM en cours...", show_time=True):
                openai_base_url = os.environ["OPENAI_BASE_URL"]
                openai_api_key = os.environ["OPENAI_API_KEY"]
                try:
                    llm_response = _call_openai_chat_completion(
                        base_url=openai_base_url,
                        api_key=openai_api_key,
                        model=model,
                        system_prompt=edited_system_prompt
                        if use_edited_system_prompt
                        else replay_payload.system_prompt,
                        user_prompt=replay_payload.user_prompt,
                        response_format=response_format,
                    )
                except Exception as e:
                    st.error(f"Erreur lors de l'appel LLM: {e}")
                    return

            content = llm_response.choices[0].message.content

            if content:
                try:
                    prediction = json.loads(content)
                    st.json(prediction)
                    _render_extraction_comparison(prediction, ground_truth)
                except Exception:
                    st.warning("Réponse du LLM non parsable en JSON:")
                    st.code(content)
                    pass


def _document_type_from_override(
    workflow: dict[str, Any], override: dict[str, Any]
) -> Any | None:
    """Return the document type configured in a workflow v2 override."""
    for params in override.values():
        if not isinstance(params, list):
            continue
        for parameter in params:
            if parameter.get("param") in {"document_type", "document-type"}:
                value = parameter.get("value")
                if value:
                    try:
                        return SupportedDocumentType.from_str(value)
                    except ValueError:
                        return None

    for step in workflow.get("steps", []):
        parameter = step.get("params", {}).get("document_type")
        if parameter and parameter.get("default"):
            try:
                return SupportedDocumentType.from_str(parameter["default"])
            except ValueError:
                return None
    return None


def main() -> None:
    title = "Amélioration du prompt d'extraction (Workflow API)"
    st.set_page_config(page_title=title, page_icon="🔄")
    st.title(title)
    st.caption(
        f"Workflow API · API endpoint: {config.DOCUMENT_IA_BASE_URL} · "
        f"Label Studio URL: {config.LABEL_STUDIO_URL}"
    )

    if not render_configuration_warnings():
        return

    api_key = config.DOCUMENT_IA_API_KEY

    selected_workflow, override = render_workflow_configurator(
        config.DOCUMENT_IA_API_KEY, key_suffix="_prompt_playground"
    )
    if selected_workflow is None:
        return

    project_selection = render_project_selector(
        client_type=ClientType.SDK,
        label="Sélectionnez un dataset Label Studio",
        show_details=True,
        show_task_count=True,
    )
    if project_selection is None:
        return

    ls_client = get_client(ClientType.SDK)

    tasks = list(
        ls_client.tasks.list(project=project_selection.project_id, fields="all")
    )
    tasks_by_id = {task.id: task for task in tasks}
    task_options = {
        task.id: f"Task {task.id} · {_extract_filename_from_task_url((task.data or {}).get('pdf'))}"
        for task in tasks
    }
    if not task_options:
        st.warning("Aucune tâche trouvée dans ce dataset.")
        return
    selected_task_id = st.selectbox(
        "Sélectionnez une task",
        options=list(task_options),
        format_func=lambda task_id: task_options[task_id],
        key="prompt_playground_task",
    )
    selected_task = tasks_by_id[selected_task_id]
    selected_document_url = (selected_task.data or {}).get("pdf")
    document_column, payload_column = st.columns(2)
    with document_column:
        st.subheader("Document sélectionné")
        if selected_document_url:
            try:
                render_browser_pdf(selected_document_url, height=650)
            except Exception as exc:
                st.error(f"Impossible d'afficher le document : {exc}")
        else:
            st.warning("Aucun document associé à cette task.")

    with payload_column:
        st.subheader("Payload du workflow")
        st.json({"workflow_id": selected_workflow["id"], "override": override})

    if st.button("Lancer l'exécution du workflow", type="primary"):
        with st.spinner("Exécution du workflow...", show_time=True):
            progress = st.progress(0, text="Executing workflow...")
            processing_results = run_workflow_on_dataset_v2(
                workflow_id=selected_workflow["id"],
                project_id=project_selection.project_id,
                api_key=api_key,
                ls_client=ls_client,
                override=override or None,
                model_version=selected_workflow["id"],
                tasks=[selected_task],
                on_progress=lambda current, total: progress.progress(current / total),
            )

        _render_processing_results(processing_results)
        state = _load_persisted_state()
        _store_execution_mapping(
            state=state,
            processing_results=processing_results,
            tasks_by_id=tasks_by_id,
            workflow_id=selected_workflow["id"],
            project_id=project_selection.project_id,
            project_title=project_selection.project_title,
            model_version=selected_workflow["id"],
            selected_doc_type=_document_type_from_override(selected_workflow, override),
        )
        _save_persisted_state(state)

    st.divider()
    _render_latest_inference_section(
        state=_load_persisted_state(),
        tasks_by_id=tasks_by_id,
        project_id=project_selection.project_id,
        task_id=selected_task_id,
    )


if __name__ == "__main__":
    main()
