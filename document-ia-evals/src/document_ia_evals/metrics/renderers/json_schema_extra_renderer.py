import json
from collections import defaultdict
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import streamlit as st

from document_ia_evals.metrics.json_schema_extra import JsonSchemaExtraObservation


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