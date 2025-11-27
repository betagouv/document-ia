"""Metrics registry for experiment evaluation."""

from typing import Callable, Dict, Any, Optional, TypeVar, ParamSpec
import importlib
import pkgutil
from pathlib import Path

# Type variables for generic decorator typing
P = ParamSpec('P')
R = TypeVar('R')


class MetricRegistry:
    """Registry for metrics used in experiments."""
    
    def __init__(self):
        self._metrics: Dict[str, Dict[str, Any]] = {}
    
    def register(
        self,
        name: str,
        description: str,
        metric_type: str = "standard",
        require: Optional[list[str]] = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Decorator to register a metric.
        
        Args:
            name: Unique metric identifier
            description: Human-readable description
            metric_type: Type of metric (e.g., "llm", "standard")
            require: List of required fields from task data
        
        Returns:
            Decorator function
        """
        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            self._metrics[name] = {
                "func": func,
                "name": name,
                "description": description,
                "metric_type": metric_type,
                "require": require or [],
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


# Global metric registry instance
metric_registry = MetricRegistry()


def auto_discover_metrics():
    """Automatically discover and import all metrics in the metrics package."""
    metrics_path = Path(__file__).parent
    
    for _, module_name, _ in pkgutil.iter_modules([str(metrics_path)]):
        if module_name.startswith('_'):
            continue
        
        try:
            importlib.import_module(f"document_ia_evals.metrics.{module_name}")
        except Exception as e:
            print(f"Warning: Failed to import metric module {module_name}: {e}")


# Auto-discover metrics when the package is imported
auto_discover_metrics()