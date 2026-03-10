# Metrics Architecture Guide

This document explains the architecture for creating and registering metrics in the document-ia-evals project.

## 📁 Structure Overview

```
metrics/
├── __init__.py                    # MetricRegistry, MetricName enum, auto-discovery
├── compare_functions.py           # Shared comparison utilities
├── utils/                         # Shared metric utilities
│   └── pydantic_helpers.py
└── {metric_name}/                 # One package per metric
    ├── __init__.py                # Public API exports
    ├── models.py                  # Data models (optional)
    ├── metric.py                  # Computation logic
    └── renderer.py                # Streamlit rendering (optional)
```

## 🎯 Design Principles

1. **Separation of Concerns**: Computation logic (`metric.py`) is separate from rendering logic (`renderer.py`)
2. **Type Safety**: All metric names use the `MetricName` enum to prevent typos and enable IDE autocomplete
3. **Package-Per-Metric**: Each metric is a self-contained package with clear boundaries
4. **Auto-Discovery**: Metrics are automatically discovered and registered on import

## 🔧 Creating a New Metric

### Step 1: Add to MetricName Enum

First, register your metric name in `metrics/__init__.py`:

```python
class MetricName(str, Enum):
    """Registry of all available metric names."""
    JSON_SCHEMA_EXTRA = "json_schema_extra"
    YOUR_NEW_METRIC = "your_new_metric"  # ⭐ Add here
```

### Step 2: Create Package Structure

Create a new package directory:

```bash
mkdir -p metrics/your_new_metric
touch metrics/your_new_metric/__init__.py
touch metrics/your_new_metric/metric.py
touch metrics/your_new_metric/renderer.py  # Optional
touch metrics/your_new_metric/models.py    # Optional
```

### Step 3: Implement the Metric

#### `metrics/your_new_metric/models.py` (Optional)

Define data models for your metric observations:

```python
"""Data models for your_new_metric."""

from typing import Dict, Any, Optional
from pydantic import BaseModel


class YourMetricObservation(BaseModel):
    """Observation model for your_new_metric."""
    
    score: float
    details: Dict[str, Any] = {}
    error: Optional[str] = None
```

#### `metrics/your_new_metric/metric.py` (Required)

Implement the computation logic:

```python
"""Your new metric computation logic."""

from typing import Any, Tuple
from document_ia_evals.metrics import metric_registry, MetricName
from .models import YourMetricObservation  # If you have models


@metric_registry.register(
    name=MetricName.YOUR_NEW_METRIC,  # ⭐ Use enum, not string
    description="Description of what your metric does",
    metric_type="standard",  # or "llm", "pydantic_comparison", etc.
    require=["field1", "field2"],  # Required fields from task data
)
def your_new_metric(
    field1: Any,
    field2: Any,
    **kwargs: Any
) -> Tuple[float, str, Any]:
    """
    Compute your metric.
    
    Args:
        field1: First required field
        field2: Second required field
        **kwargs: Additional optional parameters
    
    Returns:
        Tuple of (score, observation_json, prediction)
    """
    try:
        # Your computation logic here
        score = compute_score(field1, field2)
        
        obs = YourMetricObservation(
            score=score,
            details={"field1": field1, "field2": field2}
        )
        
        return score, obs.model_dump_json(indent=2), field1
        
    except Exception as e:
        obs = YourMetricObservation(
            score=0.0,
            error=f"Error: {str(e)}"
        )
        return 0.0, obs.model_dump_json(indent=2), field1


def compute_score(field1: Any, field2: Any) -> float:
    """Helper function for score computation."""
    # Your logic here
    return 1.0
```

#### `metrics/your_new_metric/renderer.py` (Optional)

Implement custom Streamlit rendering:

```python
"""Streamlit renderer for your_new_metric results."""

from typing import Any, Dict
import streamlit as st
from document_ia_evals.metrics import metric_registry, MetricName
from .models import YourMetricObservation


@metric_registry.renderer(name=MetricName.YOUR_NEW_METRIC)  # ⭐ Use enum
def render_results(experiment_results: Dict[str, Any]) -> None:
    """Render the results in Streamlit."""
    st.subheader("📊 Your Metric Results")
    
    observations = experiment_results.get("observations", [])
    
    if not observations:
        st.warning("No observations found.")
        return
    
    # Your custom rendering logic here
    for obs in observations:
        observation_str = obs.get("observation")
        if observation_str:
            try:
                obs_data = YourMetricObservation.model_validate_json(observation_str)
                st.write(f"Score: {obs_data.score}")
                # Add more custom visualization
            except Exception as e:
                st.error(f"Error parsing observation: {e}")
```

#### `metrics/your_new_metric/__init__.py` (Required)

Export the public API:

```python
"""Your new metric package."""

from .metric import your_new_metric
from .models import YourMetricObservation  # If you have models
from .renderer import render_results  # If you have a renderer

__all__ = [
    'your_new_metric',
    'YourMetricObservation',
    'render_results',
]
```

### Step 4: Test Your Metric

Your metric will be automatically discovered when the package is imported. Test it:

```python
from document_ia_evals.metrics import metric_registry, MetricName

# Check if registered
assert MetricName.YOUR_NEW_METRIC.value in metric_registry.get_metric_names()

# Get metric info
metric = metric_registry.get_metric(MetricName.YOUR_NEW_METRIC.value)
print(f"Description: {metric['description']}")

# Check if it has a renderer
has_renderer = metric_registry.has_renderer(MetricName.YOUR_NEW_METRIC.value)
print(f"Has renderer: {has_renderer}")
```

## 📋 Metric Function Signature

All metric functions must follow this signature:

```python
def metric_function(
    # Required parameters (specified in @register decorator)
    required_param1: Type1,
    required_param2: Type2,
    # Optional parameters
    **kwargs: Any
) -> Tuple[float, str, Any]:
    """
    Returns:
        Tuple of:
        - score (float): Numeric score for the metric
        - observation (str): JSON string with detailed observation data
        - prediction (Any): The prediction being evaluated
    """
    pass
```

## 🎨 Renderer Function Signature

Renderer functions should follow this signature:

```python
def render_results(experiment_results: Dict[str, Any]) -> None:
    """
    Render experiment results in Streamlit.
    
    Args:
        experiment_results: Dictionary containing:
            - observations: List of observation dicts
            - metric_name: Name of the metric
            - other experiment metadata
    """
    pass
```

## 🚀 Auto-Discovery

Metrics are automatically discovered when:
1. They are located in a package under `metrics/`
2. Decorators (`@metric_registry.register` and `@metric_registry.renderer`) are used