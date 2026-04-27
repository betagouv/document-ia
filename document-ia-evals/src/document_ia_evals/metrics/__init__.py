"""Metrics registry for experiment evaluation."""

from typing import Callable, Dict, Any, Optional, TypeVar, ParamSpec
from enum import Enum
import importlib
import pkgutil
from pathlib import Path

# Type variables for generic decorator typing
P = ParamSpec('P')
R = TypeVar('R')


class MetricName(str, Enum):
    """Registry of all available metric names."""
    JSON_SCHEMA_EXTRA = "json_schema_extra"
    CLASSIFICATION = "classification"
    # Future metrics can be added here:
    # ANOTHER_METRIC = "another_metric"


class MetricRegistry:
    """Registry for metrics and their renderers."""

    def __init__(self):
        self._metrics: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: MetricName,
        description: str,
        metric_type: str = "standard",
        require: Optional[list[str]] = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Decorator to register a metric computation function.

        Args:
            name: Metric name from MetricName enum
            description: Human-readable description
            metric_type: Type of metric (e.g., "llm", "standard", "pydantic_comparison")
            require: List of required fields from task data

        Returns:
            Decorator function
        """
        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            metric_key = name.value  # Convert enum to string for storage

            if metric_key in self._metrics:
                # Metric already exists (maybe renderer registered first)
                self._metrics[metric_key].update({
                    "func": func,
                    "description": description,
                    "metric_type": metric_type,
                    "require": require or [],
                })
            else:
                self._metrics[metric_key] = {
                    "func": func,
                    "name": metric_key,
                    "description": description,
                    "metric_type": metric_type,
                    "require": require or [],
                    "renderer": None,
                }
            return func
        return decorator

    def renderer(self, name: MetricName) -> Callable:
        """
        Decorator to register a renderer for a specific metric.

        Args:
            name: Metric name from MetricName enum

        Returns:
            Decorator function
        """
        def decorator(func: Callable) -> Callable:
            metric_key = name.value  # Convert enum to string

            if metric_key in self._metrics:
                self._metrics[metric_key]["renderer"] = func
            else:
                # Create placeholder for metric that will be registered later
                self._metrics[metric_key] = {
                    "func": None,
                    "renderer": func,
                    "name": metric_key,
                }
            return func
        return decorator

    def get_metric(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a metric by name."""
        return self._metrics.get(name)

    def list_metrics(self) -> Dict[str, Dict[str, Any]]:
        """List all registered metrics."""
        return self._metrics.copy()

    def get_metric_names(self) -> list[str]:
        """Get list of all metric names."""
        return list(self._metrics.keys())

    def get_metric_renderer(self, metric_name: str) -> Optional[Callable]:
        """
        Get the renderer function for a specific metric.

        Args:
            metric_name: Name of the metric (string for backward compatibility)

        Returns:
            Renderer function if found, None otherwise
        """
        metric = self._metrics.get(metric_name)
        return metric.get("renderer") if metric else None

    def has_renderer(self, metric_name: str) -> bool:
        """Check if a metric has a registered renderer."""
        metric = self._metrics.get(metric_name)
        return metric is not None and metric.get("renderer") is not None


# Global metric registry instance
metric_registry = MetricRegistry()


def auto_discover_metrics():
    """Automatically discover and import all metric packages/modules."""
    metrics_path = Path(__file__).parent

    for _, module_name, is_pkg in pkgutil.iter_modules([str(metrics_path)]):
        # Skip private modules and utility packages
        if module_name.startswith('_') or module_name in ('utils',):
            continue

        try:
            # Import the module/package - this will trigger decorators
            importlib.import_module(f"document_ia_evals.metrics.{module_name}")
        except Exception as e:
            print(f"Warning: Failed to import metric module {module_name}: {e}")


# Auto-discover metrics when the package is imported
auto_discover_metrics()


# Export public API
__all__ = [
    'MetricName',
    'MetricRegistry',
    'metric_registry',
]
