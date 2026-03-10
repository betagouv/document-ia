"""Helper functions for working with Pydantic models and fields."""

from typing import Any

from document_ia_schemas.field_metrics import Metric


def get_field_metric(field_info: Any) -> Metric:
    """
    Extract the metric type from a Pydantic field's json_schema_extra metadata.
    
    This function inspects a Pydantic field's metadata to determine which
    comparison metric should be used when evaluating field values.
    
    Args:
        field_info: Pydantic FieldInfo object containing field metadata
        
    Returns:
        Metric enum value (defaults to EQUALITY if no metric is specified)
        
    Example:
        ```python
        from pydantic import BaseModel, Field
        from document_ia_schemas.field_metrics import Metric
        
        class MyModel(BaseModel):
            name: str = Field(json_schema_extra={"metrics": "levenshtein_distance"})
        
        field_info = MyModel.model_fields["name"]
        metric = get_field_metric(field_info)  # Returns Metric.LEVENSHTEIN_DISTANCE
        ```
    """
    if hasattr(field_info, 'json_schema_extra') and field_info.json_schema_extra:
        metrics_value = field_info.json_schema_extra.get('metrics')
        if metrics_value:
            if isinstance(metrics_value, str):
                try:
                    return Metric(metrics_value)
                except ValueError:
                    pass
            elif isinstance(metrics_value, Metric):
                return metrics_value
    
    return Metric.EQUALITY