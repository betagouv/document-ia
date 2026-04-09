"""Helper functions for working with Pydantic models and fields."""

from typing import Any

from document_ia_schemas.field_metrics import Metric


def get_field_metrics(field_info: Any) -> list[Metric]:
    """
    Extract metrics from a Pydantic field's json_schema_extra metadata.

    Accepted input formats for ``json_schema_extra["metrics"]``:
    - str
    - list[str]
    - Metric
    - list[Metric]

    Invalid values are ignored; when nothing valid is found, defaults to [Metric.EQUALITY].
    """
    if not (hasattr(field_info, "json_schema_extra") and field_info.json_schema_extra):
        return [Metric.EQUALITY]

    metrics_value = field_info.json_schema_extra.get("metrics")
    if not metrics_value:
        return [Metric.EQUALITY]

    raw_metrics: list[Any]
    if isinstance(metrics_value, (str, Metric)):
        raw_metrics = [metrics_value]
    elif isinstance(metrics_value, list):
        raw_metrics = metrics_value
    else:
        return [Metric.EQUALITY]

    metrics: list[Metric] = []
    for raw_metric in raw_metrics:
        if isinstance(raw_metric, Metric):
            metrics.append(raw_metric)
            continue
        if isinstance(raw_metric, str):
            try:
                metrics.append(Metric(raw_metric))
            except ValueError:
                continue

    return metrics or [Metric.EQUALITY]
