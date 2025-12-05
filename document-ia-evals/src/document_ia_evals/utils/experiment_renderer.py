"""Shared utilities for rendering experiment results."""

import importlib
from typing import Any, Dict

import streamlit as st

from document_ia_evals.metrics import metric_registry


def render_experiment_results(results: Dict[str, Any], metric_name: str) -> None:
    """
    Render experiment results using metric-specific or default renderer.
    
    This function uses the metric registry to find and use a custom renderer:
    1. First, checks the metric registry for an auto-discovered renderer
    2. Falls back to the metric module's render_results function (backward compatibility)
    3. Falls back to default observation display if no custom renderer exists
    
    Args:
        results: Evaluation results dictionary containing observations
        metric_name: Name of the metric used for evaluation
    """
    # Try to get renderer from registry (auto-discovered from renderers/ directory)
    renderer_func = metric_registry.get_metric_renderer(metric_name)
    
    if renderer_func:
        try:
            # Call the registered renderer function
            renderer_func(results)
            return
        except Exception as e:
            st.error(f"Error rendering results: {str(e)}")
            # Continue to fallback
    
    # Backward compatibility: try the old location (metric module's render_results)
    metric_info = metric_registry.get_metric(metric_name)
    if metric_info:
        metric_module_name = metric_info['func'].__module__
        
        try:
            metric_module = importlib.import_module(metric_module_name)
            
            if hasattr(metric_module, 'render_results'):
                # Call the metric's render function (backward compatibility)
                metric_module.render_results(results)
                return
        except Exception as e:
            st.error(f"Error rendering results from metric module: {str(e)}")
    
    # Fallback: default rendering if no custom renderer found
    st.info("This metric doesn't have a custom render function")
    observations = results.get('observations', [])
    for idx, obs in enumerate(observations, 1):
        with st.expander(f"Observation {idx}", expanded=False):
            st.json(obs.get('observation', '{}'))