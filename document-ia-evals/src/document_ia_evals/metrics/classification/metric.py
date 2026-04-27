"""Classification metric computation logic."""

import json
from typing import Any, Tuple

from document_ia_evals.metrics import metric_registry, MetricName
from .models import ClassificationObservation


@metric_registry.register(
    name=MetricName.CLASSIFICATION,
    description="Compare predicted document type with ground truth classification",
    metric_type="classification",
    require=["prediction", "ground_truth"],
)
def classification_metric(
    prediction: dict[str, Any],
    ground_truth: dict[str, Any],
    **kwargs: Any
) -> Tuple[float, str, Any]:
    """
    Compute classification metric by comparing document types.

    Args:
        prediction: Prediction data from Label Studio
        ground_truth: Ground truth data from Label Studio

    Returns:
        Tuple of (score, observation_json, output)
    """
    try:
        # Extract document types (handling potential field name variations)
        pred_type = str(prediction.get("document_type", prediction.get("type", "unknown")))
        expected_type = str(ground_truth.get("document_type", ground_truth.get("type", "unknown")))

        # Binary score: 1.0 if match, 0.0 otherwise
        is_match = pred_type == expected_type
        score = 1.0 if is_match else 0.0

        obs = ClassificationObservation(
            score=score,
            expected_type=expected_type,
            predicted_type=pred_type,
            match=is_match
        )

        return score, obs.model_dump_json(), prediction

    except Exception as e:
        obs = ClassificationObservation(
            score=0.0,
            expected_type="error",
            predicted_type="error",
            match=False,
            error=str(e)
        )
        return 0.0, obs.model_dump_json(), prediction
