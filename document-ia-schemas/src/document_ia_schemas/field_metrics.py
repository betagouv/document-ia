"""Field comparison metrics enum for evaluation purposes."""

from enum import Enum


class Metric(str, Enum):
    """Enum defining available comparison metrics for field validation."""
    
    EQUALITY = "equality"
    LEVENSHTEIN_DISTANCE = "levenshtein_distance"
    DEEP_EQUALITY = "deep_equality"