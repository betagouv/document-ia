"""Renderer for classification metric results."""

import json
import pandas as pd
import streamlit as st
from typing import Any, Dict

from document_ia_evals.metrics import metric_registry, MetricName


@metric_registry.renderer(MetricName.CLASSIFICATION)
def render_classification_results(results: Dict[str, Any]) -> None:
    """
    Render classification evaluation results in Streamlit.

    Args:
        results: Results dictionary containing observations
    """
    observations = results.get('observations', [])
    if not observations:
        st.warning("No observations to render.")
        return

    # Parse observations into a list of dicts
    data = []
    for obs in observations:
        try:
            obs_detail = json.loads(obs['observation'])
            data.append({
                "task_id": obs['task_id'],
                "expected": obs_detail.get('expected_type'),
                "predicted": obs_detail.get('predicted_type'),
                "match": obs_detail.get('match'),
                "score": obs['score'],
                "model": obs['model_version']
            })
        except Exception:
            continue

    if not data:
        st.error("Could not parse observation data.")
        return

    df = pd.DataFrame(data)

    # 1. Accuracy Summary Table (similar to Processing Time Stats)
    st.subheader("🎯 Accuracy Statistics")
    model_stats = df.groupby('model').agg({
        'score': ['mean', 'count'],
        'match': lambda x: (x == False).sum()
    }).reset_index()

    model_stats.columns = ['Model Version', 'Accuracy', 'Total Samples', 'Errors']

    st.dataframe(
        model_stats.style.format({'Accuracy': '{:.2%}'}),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # 2. Detailed Section per Model
    st.header("🔍 Detailed Analysis per Model")

    project_id = results.get('project_id')
    from document_ia_evals.utils.label_studio import get_task_url

    for model_version in sorted(df['model'].unique()):
        with st.expander(f"📦 Model: {model_version}", expanded=True):
            model_df = df[df['model'] == model_version]

            col1, col2 = st.columns([1, 1])

            with col1:
                st.markdown("**📊 Confusion Matrix**")
                confusion_matrix = pd.crosstab(
                    model_df['expected'],
                    model_df['predicted'],
                    margins=True,
                    margins_name="Total"
                )
                st.dataframe(confusion_matrix, use_container_width=True)

            with col2:
                st.markdown(f"**❌ Classification Errors ({(model_df['match'] == False).sum()})**")
                errors_df = model_df[model_df['match'] == False]

                if not errors_df.empty:
                    display_errors = errors_df.copy()
                    if project_id:
                        display_errors['link'] = display_errors['task_id'].apply(
                            lambda x: get_task_url(project_id, x)
                        )
                        cols = ['task_id', 'expected', 'predicted', 'link']
                        display_errors = display_errors[cols]

                    st.dataframe(
                        display_errors,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "link": st.column_config.LinkColumn("View Task")
                        }
                    )
                else:
                    st.success("No errors for this model!")
