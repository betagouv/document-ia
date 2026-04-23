"""JSON Schema Extra metric computation logic."""

from typing import Any, Dict, Tuple
from pydantic import BaseModel

from document_ia_evals.metrics import metric_registry, MetricName
from document_ia_evals.metrics.compare_functions import (
    METRIC_FUNCTIONS,
    levenshtein_distance,
)
from document_ia_evals.metrics.utils.pydantic_helpers import get_field_metrics
from document_ia_schemas.field_metrics import Metric

from .models import JsonSchemaExtraObservation


def compare_pydantic_models(
    prediction: BaseModel,
    ground_truth: BaseModel
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    """Compare two Pydantic model instances field by field using specified metrics."""
    if type(prediction) is not type(ground_truth):
        raise ValueError(
            f"Models must be of the same type. "
            f"Got {type(prediction).__name__} and {type(ground_truth).__name__}"
        )
    
    field_scores: Dict[str, Dict[str, float]] = {}
    field_details: Dict[str, Dict[str, Any]] = {}

    model_fields = type(ground_truth).model_fields
    
    for field_name, field_info in model_fields.items():
        try:
            expected_value = getattr(ground_truth, field_name, None)
        except AttributeError:
            expected_value = None

        try:
            predicted_value = getattr(prediction, field_name, None)
        except AttributeError:
            predicted_value = None
        
        metric_types = get_field_metrics(field_info)
        metric_values = [metric.value for metric in metric_types]
        scores_by_metric: Dict[str, float] = {}
        distances_by_metric: Dict[str, int] = {}

        for metric_type in metric_types:
            compare_func = METRIC_FUNCTIONS[metric_type]
            score = compare_func(expected_value, predicted_value)
            metric_key = metric_type.value
            scores_by_metric[metric_key] = score

            if metric_type == Metric.LEVENSHTEIN_DISTANCE:
                expected_str = str(expected_value) if expected_value is not None else ""
                predicted_str = str(predicted_value) if predicted_value is not None else ""
                distances_by_metric[metric_key] = levenshtein_distance(
                    expected_str, predicted_str
                )

        field_scores[field_name] = scores_by_metric
        field_details[field_name] = {
            "expected": expected_value,
            "predicted": predicted_value,
            "metrics": metric_values,
            "scores": scores_by_metric,
        }
        if distances_by_metric:
            field_details[field_name]["distances"] = distances_by_metric
    
    return field_scores, field_details


@metric_registry.register(
    name=MetricName.JSON_SCHEMA_EXTRA,
    description="Compare Pydantic model instances using field-specific metrics defined in json_schema_extra",
    metric_type="pydantic_comparison",
    require=["prediction", "ground_truth", "document_type"],
)
def json_schema_extra_metric(
    prediction: dict[str, Any],
    ground_truth: dict[str, Any],
    document_type: str,
    **kwargs: Any
) -> Tuple[float, str, Any]:
    """Compare predicted Pydantic model with ground truth using field-specific metrics."""
    try:
        from document_ia_schemas import SupportedDocumentType, resolve_extract_schema
        
        assert isinstance(document_type, str), "document_type must be a string"

        try:
            doc_type_enum = SupportedDocumentType.from_str(document_type)
            schema = resolve_extract_schema(doc_type_enum.value)
            model_class = schema.document_model
        except (ValueError, ImportError) as e:
            obs = JsonSchemaExtraObservation(
                score=0.0,
                error=f"Failed to load schema for document_type '{document_type}': {str(e)}",
                field_scores={},
                field_details={},
                evaluated_fields=0,
                skipped_fields=0,
            )
            return 0.0, obs.model_dump_json(indent=2), prediction
        
        model_prediction = model_class.model_construct(**prediction, strict=False)
        model_ground_truth = model_class.model_construct(**ground_truth, strict=False)
        # model_prediction = model_class.model_validate(prediction, strict=False)
        # model_ground_truth = model_class.model_validate(ground_truth, strict=False)
        
    
        field_scores, field_details = compare_pydantic_models(model_prediction, model_ground_truth)
        
        all_scores = [
            score
            for scores_by_metric in field_scores.values()
            for score in scores_by_metric.values()
        ]
        evaluated_scores = [score for score in all_scores if score != -1.0]
        overall_score = sum(evaluated_scores) / len(evaluated_scores) if evaluated_scores else 0.0
        
        obs = JsonSchemaExtraObservation(
            score=overall_score,
            document_type=document_type,
            model_type=type(prediction).__name__,
            field_scores=field_scores,
            field_details=field_details,
            evaluated_fields=len(evaluated_scores),
            skipped_fields=len(all_scores) - len(evaluated_scores),
        )
        
        return overall_score, obs.model_dump_json(indent=2), prediction
        
    except Exception as e:
        obs = JsonSchemaExtraObservation(
            score=0.0,
            error=f"Error comparing models: {str(e)}",
            field_scores={},
            field_details={},
            evaluated_fields=0,
            skipped_fields=0,
        )
        return 0.0, obs.model_dump_json(indent=2), prediction
