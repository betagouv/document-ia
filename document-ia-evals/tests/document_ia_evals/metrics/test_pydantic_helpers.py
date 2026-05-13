from pydantic import BaseModel, Field

from document_ia_evals.metrics.json_schema_extra.metric import compare_pydantic_models
from document_ia_evals.metrics.utils.pydantic_helpers import get_field_metrics
from document_ia_schemas.field_metrics import Metric


class _MetricsModel(BaseModel):
    metric_str: str = Field(json_schema_extra={"metrics": "levenshtein_distance"})
    metric_list_str: str = Field(
        json_schema_extra={"metrics": ["compare_number", "equality"]}
    )
    metric_enum: str = Field(json_schema_extra={"metrics": Metric.STRING_DATE_EQUALITY})
    metric_list_enum: str = Field(
        json_schema_extra={"metrics": [Metric.SKIP, Metric.EQUALITY]}
    )
    metric_mixed_invalid: str = Field(
        json_schema_extra={"metrics": ["invalid_metric", Metric.LEVENSHTEIN_DISTANCE]}
    )
    metric_invalid_only: str = Field(json_schema_extra={"metrics": ["invalid_metric"]})
    metric_missing: str


def test_get_field_metrics_supports_all_requested_input_formats() -> None:
    fields = _MetricsModel.model_fields

    assert get_field_metrics(fields["metric_str"]) == [Metric.LEVENSHTEIN_DISTANCE]
    assert get_field_metrics(fields["metric_list_str"]) == [
        Metric.COMPARE_NUMBER,
        Metric.EQUALITY,
    ]
    assert get_field_metrics(fields["metric_enum"]) == [Metric.STRING_DATE_EQUALITY]
    assert get_field_metrics(fields["metric_list_enum"]) == [Metric.SKIP, Metric.EQUALITY]


def test_get_field_metrics_defaults_to_equality_when_invalid_or_missing() -> None:
    fields = _MetricsModel.model_fields

    assert get_field_metrics(fields["metric_mixed_invalid"]) == [Metric.LEVENSHTEIN_DISTANCE]
    assert get_field_metrics(fields["metric_invalid_only"]) == [Metric.EQUALITY]
    assert get_field_metrics(fields["metric_missing"]) == [Metric.EQUALITY]


def test_compare_pydantic_models_reads_metrics_as_list() -> None:
    class _ComparisonModel(BaseModel):
        name: str = Field(json_schema_extra={"metrics": ["levenshtein_distance", "equality"]})

    prediction = _ComparisonModel(name="aneme")
    ground_truth = _ComparisonModel(name="aname")

    field_scores, field_details = compare_pydantic_models(prediction, ground_truth)

    assert "name" in field_scores
    assert field_details["name"]["metrics"] == ["levenshtein_distance", "equality"]
    assert set(field_scores["name"].keys()) == {"levenshtein_distance", "equality"}
    assert field_scores["name"]["equality"] == 0.0
    assert 0.0 <= field_scores["name"]["levenshtein_distance"] <= 1.0
    assert field_details["name"]["scores"] == field_scores["name"]
    assert field_details["name"]["distances"] == {"levenshtein_distance": 1}
