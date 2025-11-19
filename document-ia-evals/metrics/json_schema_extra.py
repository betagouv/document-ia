"""JSON Schema Extra metric for comparing Pydantic models with field-specific metrics."""

import json
from typing import Any, Callable, Dict, Optional, Tuple
from pydantic import BaseModel
from deepdiff import DeepDiff
from metrics import metric_registry

# Import Metric from document_ia_schemas
try:
    from document_ia_schemas import Metric
except ImportError:
    from document_ia_schemas.field_metrics import Metric


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


# Mapping of metric types to comparison functions
METRIC_FUNCTIONS: Dict[Metric, Callable[[Any, Any], float]] = {
    Metric.EQUALITY: compare_equality,
    Metric.LEVENSHTEIN_DISTANCE: compare_levenshtein,
    Metric.DEEP_EQUALITY: compare_deep_equality,
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
        # Get field values
        expected_value = getattr(ground_truth, field_name)
        predicted_value = getattr(prediction, field_name)
        
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
        
        # Calculate overall score (average of field scores)
        overall_score = sum(field_scores.values()) / len(field_scores) if field_scores else 0.0
        
        # Build observation
        observation = {
            "score": overall_score,
            "document_type": document_type,
            "model_type": type(prediction).__name__,
            "field_scores": field_scores,
            "field_details": field_details,
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
    
    # DEBUG: Display full experiment_results structure
    with st.expander("🔍 DEBUG: Full Experiment Results Data Structure", expanded=True):
        st.write("**experiment_results keys:**")
        st.write(list(experiment_results.keys()))
        
        st.write("**Full experiment_results:**")
        st.json(experiment_results)
        
        st.write("**Sample observation (first one):**")
        observations = experiment_results.get("observations", [])
        if observations:
            st.json(observations[0])
            st.write(f"**Total observations:** {len(observations)}")
        else:
            st.warning("No observations found")
    
    st.divider()
    
    observations = experiment_results.get("observations", [])
    
    # Group observations by model_version
    obs_by_model = defaultdict(list)
    for obs in observations:
        model_version = obs.get("model_version", "Unknown")
        obs_by_model[model_version].append(obs)
    
    # Get all unique model versions
    model_versions = sorted(obs_by_model.keys())
    
    if not model_versions:
        st.warning("No observations found.")
        return
    
    # Display overall comparison table across models
    st.write("## 🔍 Model Comparison Summary")
    
    model_summary_data = []
    for model_version in model_versions:
        model_obs = obs_by_model[model_version]
        scores = []
        errors = 0
        
        for obs in model_obs:
            if obs.get("observation"):
                try:
                    obs_data = json.loads(obs["observation"])
                    if "score" in obs_data:
                        scores.append(obs_data["score"])
                    if "error" in obs_data:
                        errors += 1
                except (json.JSONDecodeError, TypeError):
                    errors += 1
        
        model_summary_data.append({
            "Model Version": model_version,
            "Count": len(model_obs),
            "Mean Score": f"{np.mean(scores):.3f}" if scores else "N/A",
            "Std Dev": f"{np.std(scores):.3f}" if scores else "N/A",
            "Min Score": f"{min(scores):.3f}" if scores else "N/A",
            "Max Score": f"{max(scores):.3f}" if scores else "N/A",
            "Errors": errors
        })
    
    summary_df = pd.DataFrame(model_summary_data)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    
    st.divider()
    
    # Detailed breakdown per model
    st.write("## 📊 Detailed Results by Model")
    
    for model_version in model_versions:
        with st.expander(f"**{model_version}**", expanded=len(model_versions) == 1):
            model_obs = obs_by_model[model_version]
            
            # Collect data for this model
            all_field_names = set()
            field_scores_by_name = defaultdict(list)
            global_scores = []
            errors_count = 0
            
            for obs in model_obs:
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
            
            # Display summary metrics for this model
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Overall Score", f"{np.mean(global_scores):.3f}" if global_scores else "N/A")
            with col2:
                st.metric("Total Items", len(model_obs))
            with col3:
                st.metric("Errors", errors_count)
            
            # Display field scores for this model
            if field_scores_by_name:
                st.write("**Field Scores**")
                field_data = []
                for field_name in sorted(all_field_names):
                    scores = field_scores_by_name[field_name]
                    field_data.append({
                        "Field": field_name,
                        "Mean Score": f"{np.mean(scores):.3f}",
                        "Std Dev": f"{np.std(scores):.3f}",
                        "Min Score": f"{min(scores):.3f}",
                        "Max Score": f"{max(scores):.3f}",
                        "Count": len(scores)
                    })
                
                field_df = pd.DataFrame(field_data)
                st.dataframe(field_df, use_container_width=True, hide_index=True)
            
            # Show error details if any
            if errors_count > 0:
                with st.expander(f"Error Details ({errors_count} errors)", expanded=False):
                    for idx, obs in enumerate(model_obs):
                        if obs.get("observation"):
                            try:
                                obs_data = json.loads(obs["observation"])
                                if "error" in obs_data:
                                    st.error(f"**Task {obs.get('task_id')}:** {obs_data['error']}")
                            except:
                                pass