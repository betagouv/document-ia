"""Classification accuracy metric computation logic."""

from typing import Any, Tuple

from document_ia_evals.metrics import MetricName, metric_registry
from .models import ClassificationAccuracyObservation


@metric_registry.register(
    name=MetricName.CLASSIFICATION_ACCURACY,
    description="Compare prediction and ground truth document_type fields",
    metric_type="classification_comparison",
    require=["prediction", "ground_truth"],
)
def classification_accuracy_metric(
    prediction: dict[str, Any], ground_truth: dict[str, Any], **kwargs: Any
) -> Tuple[float, str, Any]:
    """Compare predicted document_type with ground truth document_type."""
    pred_val = prediction.get("document_type")
    gt_val = ground_truth.get("document_type")

    # Normalise values
    pred_str = str(pred_val).strip() if pred_val is not None else ""
    gt_str = str(gt_val).strip() if gt_val is not None else ""

    is_correct = (pred_str.lower() == gt_str.lower()) and (pred_str != "")
    score = 1.0 if is_correct else 0.0

    obs = ClassificationAccuracyObservation(
        score=score,
        expected=gt_str,
        predicted=pred_str,
        error=(
            None
            if pred_val is not None and gt_val is not None
            else "Missing document_type field in prediction or ground truth"
        ),
    )

    return score, obs.model_dump_json(indent=2), prediction
