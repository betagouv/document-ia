from document_ia_evals.metrics.classification.metric import (
    classification_accuracy_metric,
)
from document_ia_evals.metrics.classification.models import (
    ClassificationAccuracyObservation,
)


def test_classification_accuracy_match() -> None:
    prediction = {"document_type": "invoice"}
    ground_truth = {"document_type": "invoice"}

    score, obs_json, pred = classification_accuracy_metric(prediction, ground_truth)

    assert score == 1.0
    assert pred == prediction

    obs = ClassificationAccuracyObservation.model_validate_json(obs_json)
    assert obs.score == 1.0
    assert obs.expected == "invoice"
    assert obs.predicted == "invoice"
    assert obs.error is None


def test_classification_accuracy_case_insensitive_and_whitespace() -> None:
    prediction = {"document_type": "  INVOICE  "}
    ground_truth = {"document_type": "invoice"}

    score, obs_json, _ = classification_accuracy_metric(prediction, ground_truth)

    assert score == 1.0
    obs = ClassificationAccuracyObservation.model_validate_json(obs_json)
    assert obs.score == 1.0
    assert obs.expected == "invoice"
    assert obs.predicted == "INVOICE"
    assert obs.error is None


def test_classification_accuracy_mismatch() -> None:
    prediction = {"document_type": "receipt"}
    ground_truth = {"document_type": "invoice"}

    score, obs_json, _ = classification_accuracy_metric(prediction, ground_truth)

    assert score == 0.0
    obs = ClassificationAccuracyObservation.model_validate_json(obs_json)
    assert obs.score == 0.0
    assert obs.expected == "invoice"
    assert obs.predicted == "receipt"
    assert obs.error is None


def test_classification_accuracy_missing_fields() -> None:
    # Prediction missing document_type
    prediction = {}
    ground_truth = {"document_type": "invoice"}

    score, obs_json, _ = classification_accuracy_metric(prediction, ground_truth)

    assert score == 0.0
    obs = ClassificationAccuracyObservation.model_validate_json(obs_json)
    assert obs.score == 0.0
    assert obs.expected == "invoice"
    assert obs.predicted == ""
    assert "Missing document_type field" in obs.error
