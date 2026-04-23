"""Streamlit renderer for json_schema_extra metric results."""

import json
from collections import defaultdict
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import streamlit as st

from document_ia_evals.metrics import metric_registry, MetricName
from .models import JsonSchemaExtraObservation


def _extract_field_metric_scores(
    obs_data: JsonSchemaExtraObservation,
) -> list[tuple[str, str, float]]:
    """Return flattened (field, metric, score) rows from an observation."""
    rows: list[tuple[str, str, float]] = []
    for field_name, field_score_data in obs_data.field_scores.items():
        if isinstance(field_score_data, dict):
            for metric_name, score in field_score_data.items():
                rows.append((field_name, str(metric_name), float(score)))
    return rows


@metric_registry.renderer(name=MetricName.JSON_SCHEMA_EXTRA)
def render_results(experiment_results: Dict[str, Any]) -> None:
    """Render the results of the json_schema_extra metric, grouped by model_version."""
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
    
    # Extract field-level metrics and metric types from all observations
    field_metric_scores_by_model = defaultdict(lambda: defaultdict(list))
    all_models = set()
    
    for obs in observations:
        model_version = obs.get("model_version", "Unknown")
        all_models.add(model_version)
        observation_str = obs.get("observation")
        
        if observation_str:
            try:
                obs_data = JsonSchemaExtraObservation.model_validate_json(observation_str)
                
                for field_name, metric_name, score in _extract_field_metric_scores(obs_data):
                    field_metric_scores_by_model[(field_name, metric_name)][model_version].append(score)
                            
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    
    if field_metric_scores_by_model:
        # Prepare data for table
        comparison_data = []
        for field_name, metric_name in sorted(field_metric_scores_by_model.keys()):
            row = {
                'Field': field_name,
                'Metric': metric_name
            }
            
            # Calculate mean for each model
            has_skip = False
            for model_version in sorted(all_models):
                scores = field_metric_scores_by_model[(field_name, metric_name)].get(model_version, [])
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
        
        all_field_metric_names: set[tuple[str, str]] = set()
        field_scores_by_name: Dict[tuple[str, str], list[float]] = {}
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
                    
                    for field_name, metric_name, score in _extract_field_metric_scores(obs_data):
                        key = (field_name, metric_name)
                        all_field_metric_names.add(key)
                        if key not in field_scores_by_name:
                            field_scores_by_name[key] = []
                        field_scores_by_name[key].append(score)
                    
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
            
            field_data: list[Dict[str, Any]] = []
            for field_name, metric_name in sorted(all_field_metric_names):
                scores: list[float] = field_scores_by_name[(field_name, metric_name)]
                is_skipped: bool = all(s == -1.0 for s in scores)

                if is_skipped:
                    field_data.append({
                        "Field": field_name,
                        "Metric": metric_name,
                        "Mean": "SKIPPED",
                        "Std Dev": "SKIPPED",
                        "Min": "SKIPPED",
                        "Max": "SKIPPED",
                        "Count": len(scores)
                    })
                else:
                    field_data.append({
                        "Field": field_name,
                        "Metric": metric_name,
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
