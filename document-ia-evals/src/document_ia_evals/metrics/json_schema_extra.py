"""JSON Schema Extra metric for comparing Pydantic models with field-specific metrics."""

import json
from typing import Any, Dict, Optional, Tuple

from document_ia_schemas.field_metrics import Metric
from pydantic import BaseModel
from document_ia_evals.metrics import metric_registry
from document_ia_evals.metrics.compare_functions import METRIC_FUNCTIONS, levenshtein_distance


class JsonSchemaExtraObservation(BaseModel):
    score: float
    document_type: Optional[str] = None
    model_type: Optional[str] = None
    field_scores: Dict[str, float] = {}
    field_details: Dict[str, Dict[str, Any]] = {}
    evaluated_fields: int = 0
    skipped_fields: int = 0
    error: Optional[str] = None


def get_field_metric(field_info: Any) -> Metric:
    """Extract the metric type from a field's json_schema_extra."""
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


def compare_pydantic_models(
    prediction: BaseModel,
    ground_truth: BaseModel
) -> Tuple[Dict[str, float], Dict[str, Dict[str, Any]]]:
    """Compare two Pydantic model instances field by field using specified metrics."""
    if type(prediction) != type(ground_truth):
        raise ValueError(
            f"Models must be of the same type. "
            f"Got {type(prediction).__name__} and {type(ground_truth).__name__}"
        )
    
    field_scores: Dict[str, float] = {}
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
        
        metric_type = get_field_metric(field_info) or Metric.EQUALITY
        compare_func = METRIC_FUNCTIONS[metric_type]
        score = compare_func(expected_value, predicted_value)
        
        field_scores[field_name] = score
        field_details[field_name] = {
            "expected": expected_value,
            "predicted": predicted_value,
            "metric": metric_type.value,
            "score": score,
        }
        
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
        
        evaluated_scores = {k: v for k, v in field_scores.items() if v != -1.0}
        overall_score = sum(evaluated_scores.values()) / len(evaluated_scores) if evaluated_scores else 0.0
        
        obs = JsonSchemaExtraObservation(
            score=overall_score,
            document_type=document_type,
            model_type=type(prediction).__name__,
            field_scores=field_scores,
            field_details=field_details,
            evaluated_fields=len(evaluated_scores),
            skipped_fields=len(field_scores) - len(evaluated_scores),
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


def render_results(experiment_results: Dict[str, Any]) -> None:
    """Render the results of the json_schema_extra metric, grouped by model_version."""
    import numpy as np
    import pandas as pd
    import streamlit as st
    
    st.subheader("📝 Pydantic Model Comparison Analysis")
    
    observations: list[Dict[str, Any]] = experiment_results.get("observations", [])
    
    if not observations:
        st.warning("No observations found.")
        return
    
    obs_by_model: Dict[str, list[Dict[str, Any]]] = {}
    for obs in observations:
        model_version: str = obs.get("model_version", "Unknown")
        if model_version not in obs_by_model:
            obs_by_model[model_version] = []
        obs_by_model[model_version].append(obs)
    
    model_versions: list[str] = sorted(obs_by_model.keys())
    
    st.info(f"📊 Found **{len(model_versions)}** model version(s): {', '.join(model_versions)}")
    st.divider()
    
    # Add Field-Level Metrics Comparison by Model table
    st.write("## 📊 Field-Level Metrics Comparison by Model")
    
    from collections import defaultdict
    
    # Extract field-level metrics and metric types from all observations
    field_scores_by_model = defaultdict(lambda: defaultdict(list))
    field_metrics_all = defaultdict(set)
    all_models = set()
    
    for obs in observations:
        model_version = obs.get("model_version", "Unknown")
        all_models.add(model_version)
        observation_str = obs.get("observation")
        
        if observation_str:
            try:
                obs_data = JsonSchemaExtraObservation.model_validate_json(observation_str)
                
                for field_name, field_score in obs_data.field_scores.items():
                    field_scores_by_model[field_name][model_version].append(float(field_score))
                    
                    # Extract metric type from field_details
                    if field_name in obs_data.field_details:
                        details = obs_data.field_details[field_name]
                        if "metric" in details:
                            field_metrics_all[field_name].add(str(details["metric"]))
                            
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    
    if field_scores_by_model:
        # Prepare data for table
        comparison_data = []
        for field_name in sorted(field_scores_by_model.keys()):
            # Get metric type(s) for this field
            metrics = field_metrics_all.get(field_name, set())
            metric_str = ", ".join(sorted(metrics)) if metrics else "N/A"
            
            row = {
                'Field': field_name,
                'Metric': metric_str
            }
            
            # Calculate mean for each model
            has_skip = False
            for model_version in sorted(all_models):
                scores = field_scores_by_model[field_name].get(model_version, [])
                if scores:
                    # Check if all scores are -1.0 (skipped)
                    if all(s == -1.0 for s in scores):
                        row[model_version] = "SKIPPED"
                        has_skip = True
                    else:
                        mean_value = np.mean(scores)
                        row[model_version] = f"{mean_value:.3f}"
                else:
                    row[model_version] = "SKIPPED"
                    has_skip = True
            
            row['_has_skip'] = has_skip
            comparison_data.append(row)
        
        if comparison_data:
            # Remove the helper column before displaying
            for row in comparison_data:
                del row['_has_skip']
            
            comparison_df = pd.DataFrame(comparison_data)
            
            def highlight_skip_rows(row: pd.Series) -> list[str]:
                # Check if any value in the row is "SKIPPED"
                if any(val == "SKIPPED" for val in row.values):
                    return ['background-color: #FFF3CD; color: #856404'] * len(row)
                return [''] * len(row)
            
            styled_comparison_df = comparison_df.style.apply(highlight_skip_rows, axis=1)
            st.dataframe(styled_comparison_df, use_container_width=True, hide_index=True)
    
    st.divider()
    
    for model_version in model_versions:
        st.write(f"## 🤖 Model: `{model_version}`")
        
        model_obs: list[Dict[str, Any]] = obs_by_model[model_version]
        
        all_field_names: set[str] = set()
        field_scores_by_name: Dict[str, list[float]] = {}
        global_scores: list[float] = []
        processing_times: list[float] = []
        errors_count: int = 0
        
        for obs in model_obs:
            processing_time: Optional[float] = obs.get("processing_time_ms")
            if processing_time is not None:
                processing_times.append(processing_time)
            
            observation_str: Optional[str] = obs.get("observation")
            if observation_str:
                try:
                    obs_data = JsonSchemaExtraObservation.model_validate_json(observation_str)
                    global_scores.append(obs_data.score)
                    
                    for field_name, field_score in obs_data.field_scores.items():
                        all_field_names.add(field_name)
                        if field_name not in field_scores_by_name:
                            field_scores_by_name[field_name] = []
                        field_scores_by_name[field_name].append(float(field_score))
                    
                    if obs_data.error:
                        errors_count += 1
                except (json.JSONDecodeError, TypeError, ValueError):
                    errors_count += 1
        
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
        
        if field_scores_by_name:
            st.write("### Field-Level Scores")
            
            field_metrics: Dict[str, set[str]] = {}
            for obs in model_obs:
                observation_str = obs.get("observation")
                if observation_str:
                    try:
                        obs_data = JsonSchemaExtraObservation.model_validate_json(observation_str)
                        for field_name, details in obs_data.field_details.items():
                            if "metric" in details:
                                if field_name not in field_metrics:
                                    field_metrics[field_name] = set()
                                field_metrics[field_name].add(str(details["metric"]))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
            
            field_data: list[Dict[str, Any]] = []
            for field_name in sorted(all_field_names):
                scores: list[float] = field_scores_by_name[field_name]
                is_skipped: bool = all(s == -1.0 for s in scores)
                
                metrics: set[str] = field_metrics.get(field_name, set())
                metric_str: str = ", ".join(sorted(metrics)) if metrics else "N/A"
                
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
            
            def highlight_skipped(row: pd.Series) -> list[str]:
                if row['Mean'] == 'SKIPPED':
                    return ['background-color: #FFF3CD; color: #856404'] * len(row)
                return [''] * len(row)
            
            styled_df = field_df.style.apply(highlight_skipped, axis=1)
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        if errors_count > 0:
            with st.expander(f"⚠️ Error Details ({errors_count} errors)"):
                for obs in model_obs:
                    observation_str = obs.get("observation")
                    if observation_str:
                        try:
                            obs_data = JsonSchemaExtraObservation.model_validate_json(observation_str)
                            if obs_data.error:
                                task_id: Any = obs.get('task_id')
                                st.error(f"**Task {task_id}:** {obs_data.error}")
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
        
        if model_version != model_versions[-1]:
            st.divider()