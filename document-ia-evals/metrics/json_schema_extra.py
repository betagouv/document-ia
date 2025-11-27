"""JSON Schema Extra metric for comparing Pydantic models with field-specific metrics."""

import json
from typing import Any, Callable, Dict, Optional, Tuple
from pydantic import BaseModel
from deepdiff import DeepDiff
from metrics import metric_registry
from document_ia_schemas.field_metrics import Metric
import re
from typing import Any

from datetime import datetime
from typing import Any

def normalize_avis_imposition_date(value: Any):
    """
    Normalize date strings that may be in DD/MM/YYYY or DDMMYYYY format.
    Returns a datetime.date object or None if parsing fails.
    """
    if value is None:
        return None

    s = str(value).strip()

    # Try DD/MM/YYYY format
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        pass

    # Try DDMMYYYY format (must be exactly 8 digits)
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%d%m%Y").date()
        except ValueError:
            pass

    return None


def compare_avis_imposition_date(expected: Any, predicted: Any) -> float:
    """
    Compare two date values that may be in formats:
    - DD/MM/YYYY
    - DDMMYYYY
    Returns 1.0 if equal, 0.0 otherwise.
    """
    d1 = normalize_avis_imposition_date(expected)
    d2 = normalize_avis_imposition_date(predicted)

    # Both must parse correctly
    if d1 is None or d2 is None:
        return 0.0

    return 1.0 if d1 == d2 else 0.0


def normalize_number(value: Any):
    """
    Normalize a number represented as a messy string.
    Handles:
      - spaces: " 1 234 " → "1234"
      - commas: "12,5" → "12.5"
      - currency symbols: "1 200 €" → "1200"
      - thousands separators: "1.234,56" → "1234.56"
    Returns:
      float or None if parsing fails.
    """
    if value is None:
        return None

    s = str(value).strip()

    if not s:
        return None

    # Remove all spaces
    s = s.replace(" ", "")

    # Replace comma with dot (decimal normalization)
    s = s.replace(",", ".")

    # Keep only digits, minus sign, and dot
    s = re.sub(r"[^0-9\.-]", "", s)

    # If multiple dots or dashes → invalid
    if s.count('.') > 1 or s.count('-') > 1:
        return None

    try:
        return float(s)
    except ValueError:
        return None


def compare_number(expected: Any, predicted: Any) -> float:
    """
    Compare two values as normalized numbers.
    Returns 1.0 if equal, otherwise 0.0.
    """
    n1 = normalize_number(expected)
    n2 = normalize_number(predicted)

    if n1 == n2:
        return 1.0
    if n1 is None or n2 is None:
        return 0.0

    return 1.0 if n1 == n2 else 0.0


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.
    
    Args:
        s1: First string
        s2: Second string
    
    Returns:
        int: The minimum number of single-character edits required to change s1 into s2
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Calculate normalized Levenshtein similarity between two strings.
    
    Args:
        s1: First string
        s2: Second string
    
    Returns:
        float: Similarity score between 0.0 and 1.0, where 1.0 is identical strings
    """
    if s1 == s2:
        return 1.0
    
    if not s1 or not s2:
        return 0.0
    
    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    
    return 1.0 - (distance / max_len)


def compare_equality(expected: Any, predicted: Any) -> float:
    """
    Compare two values for exact equality.
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: 1.0 if equal, 0.0 otherwise
    """
    return 1.0 if expected == predicted else 0.0


def compare_levenshtein(expected: Any, predicted: Any) -> float:
    """
    Compare two values using Levenshtein distance (for strings).
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: Similarity score between 0.0 and 1.0
    """
    # Convert to strings if not already
    expected_str = str(expected) if expected is not None else ""
    predicted_str = str(predicted) if predicted is not None else ""
    
    return levenshtein_similarity(expected_str, predicted_str)


def compare_deep_equality(expected: Any, predicted: Any) -> float:
    """
    Compare two complex values using deep comparison (for nested structures).
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: Similarity score based on structural comparison
    """
    diff = DeepDiff(expected, predicted, ignore_order=True)
    
    # If no differences, return perfect score
    if not diff:
        return 1.0
    
    return 0.0

def skip(expected: Any, predicted: Any) -> float:
    return -1.0


# Mapping of metric types to comparison functions
METRIC_FUNCTIONS: Dict[Metric, Callable[[Any, Any], float]] = {
    Metric.EQUALITY: compare_equality,
    Metric.LEVENSHTEIN_DISTANCE: compare_levenshtein,
    Metric.DEEP_EQUALITY: compare_deep_equality,
    Metric.AVIS_IMPOSITION_DATE_EQUALITY: compare_avis_imposition_date,
    Metric.COMPARE_NUMBER: compare_number,
    Metric.SKIP: skip
}


def get_field_metric(field_info: Any) -> Metric:
    """
    Extract the metric type from a field's json_schema_extra.
    
    Args:
        field_info: Pydantic field info object
    
    Returns:
        Metric: The metric to use for comparison (defaults to EQUALITY)
    """
    # Check if field has json_schema_extra
    if hasattr(field_info, 'json_schema_extra') and field_info.json_schema_extra:
        metrics_value = field_info.json_schema_extra.get('metrics')
        if metrics_value:
            # Handle both string and Metric enum values
            if isinstance(metrics_value, str):
                try:
                    return Metric(metrics_value)
                except ValueError:
                    pass
            elif isinstance(metrics_value, Metric):
                return metrics_value
    
    # Default to equality
    return Metric.EQUALITY


def compare_pydantic_models(
    prediction: BaseModel,
    ground_truth: BaseModel
) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
    """
    Compare two Pydantic model instances field by field using specified metrics.
    
    Args:
        prediction: Predicted model instance
        ground_truth: Ground truth model instance
    
    Returns:
        Tuple of (field_scores, field_details):
            - field_scores: Dict mapping field names to similarity scores (0.0 to 1.0)
            - field_details: Dict mapping field names to detailed comparison info
    """
    if type(prediction) != type(ground_truth):
        raise ValueError(
            f"Models must be of the same type. "
            f"Got {type(prediction).__name__} and {type(ground_truth).__name__}"
        )
    
    field_scores: Dict[str, float] = {}
    field_details: Dict[str, Dict[str, Any]] = {}
    
    # Get model fields
    model_fields = ground_truth.model_fields
    
    for field_name, field_info in model_fields.items():
        # Get field values with safe attribute access
        try:
            expected_value = getattr(ground_truth, field_name, None)
        except AttributeError:
            expected_value = None
            
        try:
            predicted_value = getattr(prediction, field_name, None)
        except AttributeError:
            predicted_value = None
        
        # Get the metric to use for this field
        metric_type = get_field_metric(field_info)
        
        # Get the comparison function
        compare_func = METRIC_FUNCTIONS.get(metric_type, compare_equality)
        
        # Calculate score
        score = compare_func(expected_value, predicted_value)
        
        # Store results
        field_scores[field_name] = score
        field_details[field_name] = {
            "expected": expected_value,
            "predicted": predicted_value,
            "metric": metric_type.value,
            "score": score,
        }
        
        # Add distance for Levenshtein
        if metric_type == Metric.LEVENSHTEIN_DISTANCE:
            expected_str = str(expected_value) if expected_value is not None else ""
            predicted_str = str(predicted_value) if predicted_value is not None else ""
            field_details[field_name]["distance"] = levenshtein_distance(
                expected_str, predicted_str
            )
    
    return field_scores, field_details
@metric_registry.register(
    name="json_schema_extra",
    description="Compare Pydantic model instances using field-specific metrics defined in json_schema_extra",
    metric_type="pydantic_comparison",
    require=["prediction", "ground_truth", "document_type"],
)
def json_schema_extra_metric(
    prediction: Any,
    ground_truth: Any,
    document_type: Optional[str] = None,
    **kwargs
) -> Tuple[float, str, Any]:
    """
    Compare predicted Pydantic model with ground truth using field-specific metrics.
    
    This metric reads the 'metrics' key from each field's json_schema_extra to determine
    which comparison method to use. Defaults to EQUALITY if not specified.
    
    Example field definition:
        reference_avis: Optional[str] = Field(
            default=None,
            description="Reference number",
            json_schema_extra={"metrics": Metric.LEVENSHTEIN_DISTANCE}
        )
    
    Args:
        prediction: The predicted Pydantic model instance
        ground_truth: The ground truth Pydantic model instance
        **kwargs: Additional parameters (unused)
    
    Returns:
        Tuple of (score, observation_json, output):
            - score: Overall similarity score (0.0 to 1.0)
            - observation_json: JSON string with detailed field-level results
            - output: The prediction for reference
    """
    try:
        # Import resolve_extract_schema to get the document model
        from document_ia_schemas import resolve_extract_schema, SupportedDocumentType
        
        # If document_type is not provided, try to infer from data
        if document_type is None:
            # Try to get it from prediction or ground_truth if they have a 'type' field
            if isinstance(prediction, dict) and 'type' in prediction:
                extracted_type = prediction.get('type')
                if isinstance(extracted_type, str):
                    document_type = extracted_type
            elif isinstance(ground_truth, dict) and 'type' in ground_truth:
                extracted_type = ground_truth.get('type')
                if isinstance(extracted_type, str):
                    document_type = extracted_type
            
            if document_type is None:
                error_obs = {
                    "score": 0.0,
                    "error": "document_type parameter is required when prediction/ground_truth don't have 'type' field",
                }
                return 0.0, json.dumps(error_obs, indent=2), prediction
        
        # At this point, document_type is guaranteed to be a string
        assert isinstance(document_type, str), "document_type must be a string"
        
        # Get the schema for the document type
        try:
            doc_type_enum = SupportedDocumentType.from_str(document_type)
            schema = resolve_extract_schema(doc_type_enum.value)
            model_class = schema.document_model
        except (ValueError, ImportError) as e:
            error_obs = {
                "score": 0.0,
                "error": f"Failed to load schema for document_type '{document_type}': {str(e)}",
            }
            return 0.0, json.dumps(error_obs, indent=2), prediction
        
        # Convert dict inputs to Pydantic models if needed
        # Use model_construct to bypass validation and accept Python field names
        if isinstance(prediction, dict):
            try:
                # First try with model_validate and by_alias=False for proper validation
                try:
                    prediction = model_class.model_validate(prediction, strict=False)
                except Exception:
                    # If that fails, use model_construct which accepts any field names
                    prediction = model_class.model_construct(**prediction)
            except Exception as e:
                error_obs = {
                    "score": 0.0,
                    "error": f"Failed to create prediction model {model_class.__name__}: {str(e)}",
                    "prediction_data": prediction,
                }
                return 0.0, json.dumps(error_obs, indent=2), prediction
        
        if isinstance(ground_truth, dict):
            try:
                # First try with model_validate and by_alias=False for proper validation
                try:
                    ground_truth = model_class.model_validate(ground_truth, strict=False)
                except Exception:
                    # If that fails, use model_construct which accepts any field names
                    ground_truth = model_class.model_construct(**ground_truth)
            except Exception as e:
                error_obs = {
                    "score": 0.0,
                    "error": f"Failed to create ground_truth model {model_class.__name__}: {str(e)}",
                    "ground_truth_data": ground_truth,
                }
                return 0.0, json.dumps(error_obs, indent=2), prediction
        
        # Validate inputs are now Pydantic models
        if not isinstance(prediction, BaseModel):
            error_obs = {
                "score": 0.0,
                "error": f"Prediction must be a Pydantic BaseModel instance, got {type(prediction).__name__}",
            }
            return 0.0, json.dumps(error_obs, indent=2), prediction
        
        if not isinstance(ground_truth, BaseModel):
            error_obs = {
                "score": 0.0,
                "error": f"Ground truth must be a Pydantic BaseModel instance, got {type(ground_truth).__name__}",
            }
            return 0.0, json.dumps(error_obs, indent=2), prediction
        
        # Check that models are of the same type
        if type(prediction) != type(ground_truth):
            error_obs = {
                "score": 0.0,
                "error": (
                    f"Models must be of the same type. "
                    f"Prediction is {type(prediction).__name__}, "
                    f"ground truth is {type(ground_truth).__name__}"
                ),
            }
            return 0.0, json.dumps(error_obs, indent=2), prediction
    
        # Compare models field by field
        field_scores, field_details = compare_pydantic_models(prediction, ground_truth)
        
        # Filter out skipped fields (score == -1.0) when calculating overall score
        evaluated_scores = {k: v for k, v in field_scores.items() if v != -1.0}
        
        # Calculate overall score (average of non-skipped field scores)
        overall_score = sum(evaluated_scores.values()) / len(evaluated_scores) if evaluated_scores else 0.0
        
        # Build observation
        observation = {
            "score": overall_score,
            "document_type": document_type,
            "model_type": type(prediction).__name__,
            "field_scores": field_scores,
            "field_details": field_details,
            "evaluated_fields": len(evaluated_scores),
            "skipped_fields": len(field_scores) - len(evaluated_scores),
        }
        
        return overall_score, json.dumps(observation, indent=2), prediction
        
    except Exception as e:
        error_obs = {
            "score": 0.0,
            "error": f"Error comparing models: {str(e)}",
        }
        return 0.0, json.dumps(error_obs, indent=2), prediction


def render_results(experiment_results: Dict[str, Any]) -> None:
    """
    Render the results of the json_schema_extra metric, grouped by model_version.
    
    Args:
        experiment_results: Dictionary containing experiment data with observations
    """
    import streamlit as st
    import pandas as pd
    from collections import defaultdict
    import numpy as np
    
    st.subheader("📝 Pydantic Model Comparison Analysis")
    
    observations = experiment_results.get("observations", [])
    
    if not observations:
        st.warning("No observations found.")
        return
    
    # Group observations by model_version
    obs_by_model = defaultdict(list)
    for obs in observations:
        model_version = obs.get("model_version", "Unknown")
        obs_by_model[model_version].append(obs)
    
    # Get all unique model versions sorted
    model_versions = sorted(obs_by_model.keys())
    
    # Show number of models found
    st.info(f"📊 Found **{len(model_versions)}** model version(s): {', '.join(model_versions)}")
    st.divider()
    
    # Create one recap table per model_version
    for model_version in model_versions:
        st.write(f"## 🤖 Model: `{model_version}`")
        
        model_obs = obs_by_model[model_version]
        
        # Collect data for this model
        all_field_names = set()
        field_scores_by_name = defaultdict(list)
        global_scores = []
        processing_times = []
        errors_count = 0
        
        for obs in model_obs:
            # Collect processing times
            processing_time = obs.get("processing_time_ms")
            if processing_time is not None:
                processing_times.append(processing_time)
            
            if obs.get("observation"):
                try:
                    obs_data = json.loads(obs["observation"])
                    if "score" in obs_data:
                        global_scores.append(obs_data["score"])
                    field_scores = obs_data.get("field_scores", {})
                    for field_name, field_score in field_scores.items():
                        if isinstance(field_score, (int, float)):
                            all_field_names.add(field_name)
                            field_scores_by_name[field_name].append(field_score)
                    if "error" in obs_data:
                        errors_count += 1
                except (json.JSONDecodeError, TypeError):
                    errors_count += 1
        
        # Summary metrics for this model
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Overall Score", f"{np.mean(global_scores):.3f}" if global_scores else "N/A")
        with col2:
            st.metric("Total Items", len(model_obs))
        with col3:
            st.metric("Errors", errors_count)
        with col4:
            if processing_times:
                st.metric("Avg Processing Time", f"{np.mean(processing_times)/1000:.0f} s")
            else:
                st.metric("Avg Processing Time", "N/A")
        
        # Processing time statistics
        if processing_times:
            st.write("### ⏱️ Processing Time Statistics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Mean", f"{(np.mean(processing_times)/1000):.2f} s")
            with col2:
                st.metric("Median", f"{np.median(processing_times)/1000:.2f} s")
            with col3:
                st.metric("Min", f"{min(processing_times)/1000:.2f} s")
            with col4:
                st.metric("Max", f"{max(processing_times)/1000:.2f} s")
        
        # Field-level scores table
        if field_scores_by_name:
            st.write("### Field-Level Scores")
            
            # Collect metrics for each field
            field_metrics = defaultdict(set)
            for obs in model_obs:
                if obs.get("observation"):
                    try:
                        obs_data = json.loads(obs["observation"])
                        field_details = obs_data.get("field_details", {})
                        for field_name, details in field_details.items():
                            if "metric" in details:
                                field_metrics[field_name].add(details["metric"])
                    except (json.JSONDecodeError, TypeError):
                        pass
            
            field_data = []
            for field_name in sorted(all_field_names):
                scores = field_scores_by_name[field_name]
                # Check if field is skipped (all scores are -1.0)
                is_skipped = all(s == -1.0 for s in scores)
                
                # Get metric(s) used for this field
                metrics = field_metrics.get(field_name, set())
                metric_str = ", ".join(sorted(metrics)) if metrics else "N/A"
                
                if is_skipped:
                    field_data.append({
                        "Field": field_name,
                        "Metric": metric_str,
                        "Mean": "SKIPPED",
                        "Std Dev": "SKIPPED",
                        "Min": "SKIPPED",
                        "Max": "SKIPPED",
                        "Count": len(scores)
                    })
                else:
                    field_data.append({
                        "Field": field_name,
                        "Metric": metric_str,
                        "Mean": f"{np.mean(scores):.3f}",
                        "Std Dev": f"{np.std(scores):.3f}",
                        "Min": f"{min(scores):.3f}",
                        "Max": f"{max(scores):.3f}",
                        "Count": len(scores)
                    })
            
            field_df = pd.DataFrame(field_data)
            
            # Apply styling to highlight skipped rows
            def highlight_skipped(row):
                if row['Mean'] == 'SKIPPED':
                    return ['background-color: #FFF3CD; color: #856404'] * len(row)
                return [''] * len(row)
            
            styled_df = field_df.style.apply(highlight_skipped, axis=1)
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # Show error details if any
        if errors_count > 0:
            with st.expander(f"⚠️ Error Details ({errors_count} errors)"):
                for obs in model_obs:
                    if obs.get("observation"):
                        try:
                            obs_data = json.loads(obs["observation"])
                            if "error" in obs_data:
                                st.error(f"**Task {obs.get('task_id')}:** {obs_data['error']}")
                        except:
                            pass
        
        # Separator between models
        if model_version != model_versions[-1]:
            st.divider()