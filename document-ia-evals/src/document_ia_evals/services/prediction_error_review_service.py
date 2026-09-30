"""Prepare Label Studio prediction error reviews for the Streamlit UI."""

import json
from dataclasses import dataclass
from typing import Any

from document_ia_evals.metrics.json_schema_extra.metric import json_schema_extra_metric
from document_ia_evals.metrics.json_schema_extra.models import JsonSchemaExtraObservation
from document_ia_evals.metrics.utils.pydantic_helpers import get_field_metrics
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema


@dataclass(frozen=True)
class FieldMetricOption:
    field: str
    metric: str


@dataclass(frozen=True)
class PredictionError:
    task_id: int | str
    prediction_id: int | str
    document_url: str | None
    field: str
    metric: str
    expected: Any
    predicted: Any
    score: float


@dataclass(frozen=True)
class ErrorReviewDocument:
    task_id: int | str
    prediction_id: int | str
    model_version: str
    document_url: str | None
    errors: tuple[PredictionError, ...]


def get_field_metric_options(document_type: str) -> list[FieldMetricOption]:
    """Return the field/metric pairs declared by the extraction schema."""
    doc_type = SupportedDocumentType.from_str(document_type)
    model = resolve_extract_schema(doc_type.value).document_model
    return [
        FieldMetricOption(field_name, metric.value)
        for field_name, field_info in model.model_fields.items()
        for metric in get_field_metrics(field_info)
        if metric.value != "skip"
    ]


def get_model_versions(tasks: list[dict[str, Any]]) -> list[str]:
    """Return distinct model versions present in Label Studio predictions."""
    versions = {
        str(prediction.get("model_version"))
        for task in tasks
        for prediction in task.get("predictions", [])
        if prediction.get("model_version")
    }
    return sorted(versions)


def get_document_url(task: dict[str, Any]) -> str | None:
    """Resolve the document URL used by the task data."""
    data = task.get("data") or {}
    for key in ("pdf_url", "pdf", "image_url", "image"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _get_ground_truth(task: dict[str, Any]) -> dict[str, Any] | None:
    from document_ia_evals.utils.label_studio import annotation_results_to_dict

    for annotation in task.get("annotations", []):
        if annotation.get("ground_truth"):
            ground_truth, _ = annotation_results_to_dict(annotation.get("result", []))
            return ground_truth
    return None


def _selected_prediction(
    task: dict[str, Any], model_version: str
) -> dict[str, Any] | None:
    predictions = [
        prediction
        for prediction in task.get("predictions", [])
        if str(prediction.get("model_version")) == model_version
    ]
    if len(predictions) != 1:
        return None
    return predictions[0]


def find_error_documents(
    tasks: list[dict[str, Any]],
    model_version: str,
    document_type: str,
    selected_pairs: set[tuple[str, str]],
) -> tuple[list[ErrorReviewDocument], list[int | str]]:
    """Compare one model's predictions and return only documents with errors.

    Tasks with no ground truth, no selected prediction, or duplicate predictions
    for the selected model are skipped. The latter are returned for display.
    """
    ambiguous_task_ids: list[int | str] = []
    documents: list[ErrorReviewDocument] = []

    if not selected_pairs:
        return [], ambiguous_task_ids

    from document_ia_evals.utils.label_studio import annotation_results_to_dict

    for task in tasks:
        task_id = task.get("id", "Unknown")
        ground_truth = _get_ground_truth(task)
        prediction = _selected_prediction(task, model_version)
        matching_predictions = [
            p
            for p in task.get("predictions", [])
            if str(p.get("model_version")) == model_version
        ]
        if len(matching_predictions) > 1:
            ambiguous_task_ids.append(task_id)
        if ground_truth is None or prediction is None:
            continue

        predicted, _ = annotation_results_to_dict(prediction.get("result", []))
        _, observation_json, _ = json_schema_extra_metric(
            prediction=predicted,
            ground_truth=ground_truth,
            document_type=document_type,
        )
        try:
            observation = JsonSchemaExtraObservation.model_validate_json(observation_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if observation.error:
            continue

        errors: list[PredictionError] = []
        for field, metric in selected_pairs:
            score = observation.field_scores.get(field, {}).get(metric)
            details = observation.field_details.get(field, {})
            if (
                score is None
                or score in (1.0, -1.0)
                or (details.get("expected") is None and details.get("predicted") is None)
            ):
                continue
            errors.append(
                PredictionError(
                    task_id=task_id,
                    prediction_id=prediction.get("id", "Unknown"),
                    document_url=get_document_url(task),
                    field=field,
                    metric=metric,
                    expected=details.get("expected"),
                    predicted=details.get("predicted"),
                    score=float(score),
                )
            )

        if errors:
            documents.append(
                ErrorReviewDocument(
                    task_id=task_id,
                    prediction_id=prediction.get("id", "Unknown"),
                    model_version=model_version,
                    document_url=get_document_url(task),
                    errors=tuple(sorted(errors, key=lambda error: (error.field, error.metric))),
                )
            )

    return documents, ambiguous_task_ids
