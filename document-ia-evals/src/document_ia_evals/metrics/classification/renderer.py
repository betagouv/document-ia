"""Streamlit renderer for classification accuracy metric results."""

import json
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import streamlit as st

from document_ia_evals.metrics import metric_registry, MetricName
from .models import ClassificationAccuracyObservation


@metric_registry.renderer(name=MetricName.CLASSIFICATION_ACCURACY)
def render_results(experiment_results: Dict[str, Any]) -> None:
    """Render the results of the classification accuracy metric, grouped by model_version."""
    st.subheader("🎯 Classification Accuracy Analysis")

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

    st.info(
        f"📊 Found **{len(model_versions)}** model version(s): {', '.join(model_versions)}"
    )
    st.divider()

    for model_version in model_versions:
        st.write(f"## 🤖 Model: `{model_version}`")

        model_obs: list[Dict[str, Any]] = obs_by_model[model_version]

        global_scores: list[float] = []
        processing_times: list[float] = []
        errors_count: int = 0
        details_data: list[Dict[str, Any]] = []

        for obs in model_obs:
            processing_time: Optional[float] = obs.get("processing_time_ms")
            if processing_time is not None:
                processing_times.append(processing_time)

            task_id = obs.get("task_id", "Unknown")
            observation_str: Optional[str] = obs.get("observation")

            if observation_str:
                try:
                    obs_data = ClassificationAccuracyObservation.model_validate_json(
                        observation_str
                    )
                    global_scores.append(obs_data.score)

                    details_data.append(
                        {
                            "Task ID": task_id,
                            "Expected": obs_data.expected or "N/A",
                            "Predicted": obs_data.predicted or "N/A",
                            "Result": "✅ Match"
                            if obs_data.score == 1.0
                            else "❌ Mismatch",
                            "Score": f"{obs_data.score:.1f}",
                        }
                    )

                    if obs_data.error:
                        errors_count += 1
                except (json.JSONDecodeError, TypeError, ValueError):
                    errors_count += 1
                    details_data.append(
                        {
                            "Task ID": task_id,
                            "Expected": "Error",
                            "Predicted": "Error",
                            "Result": "⚠️ Error parsing observation",
                            "Score": "0.0",
                        }
                    )
            else:
                errors_count += 1
                details_data.append(
                    {
                        "Task ID": task_id,
                        "Expected": "N/A",
                        "Predicted": "N/A",
                        "Result": "⚠️ Missing observation",
                        "Score": "0.0",
                    }
                )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            accuracy = np.mean(global_scores) if global_scores else 0.0
            st.metric(
                "Accuracy Rate", f"{accuracy * 100:.1f}%" if global_scores else "N/A"
            )
        with col2:
            st.metric("Total Items", len(model_obs))
        with col3:
            st.metric("Errors", errors_count)
        with col4:
            if processing_times:
                st.metric(
                    "Avg Processing Time", f"{np.mean(processing_times) / 1000:.2f} s"
                )
            else:
                st.metric("Avg Processing Time", "N/A")

        if processing_times:
            st.write("### ⏱️ Processing Time Statistics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Mean", f"{(np.mean(processing_times) / 1000):.2f} s")
            with col2:
                st.metric("Median", f"{np.median(processing_times) / 1000:.2f} s")
            with col3:
                st.metric("Min", f"{min(processing_times) / 1000:.2f} s")
            with col4:
                st.metric("Max", f"{max(processing_times) / 1000:.2f} s")

        if details_data:
            st.write("### 📋 Classification Details")
            details_df = pd.DataFrame(details_data)

            def highlight_results(row: pd.Series) -> list[str]:
                if "❌ Mismatch" in row["Result"]:
                    return ["background-color: #F8D7DA; color: #721C24"] * len(row)
                elif "⚠️" in row["Result"]:
                    return ["background-color: #FFF3CD; color: #856404"] * len(row)
                return [""] * len(row)

            styled_details_df = details_df.style.apply(highlight_results, axis=1)
            st.dataframe(styled_details_df, use_container_width=True, hide_index=True)

        if errors_count > 0:
            with st.expander(f"⚠️ Error Details ({errors_count} errors)"):
                for obs in model_obs:
                    observation_str = obs.get("observation")
                    if observation_str:
                        try:
                            obs_data = (
                                ClassificationAccuracyObservation.model_validate_json(
                                    observation_str
                                )
                            )
                            if obs_data.error:
                                task_id = obs.get("task_id")
                                st.error(f"**Task {task_id}:** {obs_data.error}")
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass

        if model_version != model_versions[-1]:
            st.divider()
