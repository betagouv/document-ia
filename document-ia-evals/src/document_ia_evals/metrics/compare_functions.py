"""JSON Schema Extra metric for comparing Pydantic models with field-specific metrics."""

import re
from datetime import datetime
from typing import Any, Callable, Dict

from deepdiff import DeepDiff
from document_ia_schemas.field_metrics import Metric


def normalize_string_date(value: Any):
    """
    Normalize date strings in various formats (European and ISO).
    
    Supported formats:
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, DDMMYYYY (European)
    - YYYY/MM/DD, YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD (ISO)
    
    Returns a datetime.date object or None if parsing fails.
    """
    if value is None:
        return None

    s = str(value).strip()

    # Try DD/MM/YYYY format
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        pass

    # Try DD-MM-YYYY format
    try:
        return datetime.strptime(s, "%d-%m-%Y").date()
    except ValueError:
        pass

    # Try DD.MM.YYYY format
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except ValueError:
        pass

    # Try DDMMYYYY format (must be exactly 8 digits)
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%d%m%Y").date()
        except ValueError:
            pass
    
    # Try YYYY/MM/DD format
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        pass

    # Try YYYY-MM-DD format
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Try YYYY.MM.DD format
    try:
        return datetime.strptime(s, "%Y.%m.%d").date()
    except ValueError:
        pass

    # Try YYYYMMDD format (must be exactly 8 digits)
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d").date()
        except ValueError:
            pass

    return None


def compare_string_date(expected: Any, predicted: Any) -> float:
    """
    Compare two date values that may be in various formats.
    
    Supported formats:
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, DDMMYYYY (European)
    - YYYY/MM/DD, YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD (ISO)
    
    Returns 1.0 if equal, 0.0 otherwise.
    """
    d1 = normalize_string_date(expected)
    d2 = normalize_string_date(predicted)

    # Both must parse correctly
    if d1 is None or d2 is None:
        return 0.0

    return 1.0 if d1 == d2 else 0.0


def normalize_number(value: Any):
    """
    Normalize a number represented as a messy string.
    Handles:
      - spaces: " 1 234 567 " → "1234567"
      - commas: "12,5" → "12.5"
      - currency symbols: "1 200 €" → "1200"
      - thousands separators: "1.234,56" → "1234.56"
      - minus sign: "1234-56" → "123456"
    Returns:
      float or None if parsing fails.
    """
    if value is None:
        return None

    s = str(value).strip()

    if not s:
        return None

    # Remove all spaces
    s = s.replace(" ", "")

    # Replace comma with dot (decimal normalization)
    s = s.replace(",", ".")

    # Keep only digits, minus sign, and dot
    s = re.sub(r"[^0-9\.-]", "", s)

    # If multiple dots or dashes → invalid
    if s.count('.') > 1 or s.count('-') > 1:
        return None

    try:
        return float(s)
    except ValueError:
        return None


def compare_number(expected: Any, predicted: Any) -> float:
    """
    Compare two values as normalized numbers.
    Returns 1.0 if equal, otherwise 0.0.
    """
    n1 = normalize_number(expected)
    n2 = normalize_number(predicted)

    if n1 == n2:
        return 1.0
    if n1 is None or n2 is None:
        return 0.0

    return 1.0 if n1 == n2 else 0.0


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.
    
    Args:
        s1: First string
        s2: Second string
    
    Returns:
        int: The minimum number of single-character edits required to change s1 into s2
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Calculate normalized Levenshtein similarity between two strings.
    
    Args:
        s1: First string
        s2: Second string
    
    Returns:
        float: Similarity score between 0.0 and 1.0, where 1.0 is identical strings
    """
    if s1 == s2:
        return 1.0
    
    if not s1 or not s2:
        return 0.0
    
    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    
    return 1.0 - (distance / max_len)


def compare_equality(expected: Any, predicted: Any) -> float:
    """
    Compare two values for exact equality.
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: 1.0 if equal, 0.0 otherwise
    """
    return 1.0 if expected == predicted else 0.0


def compare_levenshtein(expected: Any, predicted: Any) -> float:
    """
    Compare two values using Levenshtein distance (for strings).
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: Similarity score between 0.0 and 1.0
    """
    # Convert to strings if not already
    expected_str = str(expected) if expected is not None else ""
    predicted_str = str(predicted) if predicted is not None else ""
    
    return levenshtein_similarity(expected_str, predicted_str)


def compare_deep_equality(expected: Any, predicted: Any) -> float:
    """
    Compare two complex values using deep comparison (for nested structures).
    
    Args:
        expected: Ground truth value
        predicted: Predicted value
    
    Returns:
        float: Similarity score based on structural comparison
    """
    diff = DeepDiff(expected, predicted, ignore_order=True)
    
    # If no differences, return perfect score
    if not diff:
        return 1.0
    
    return 0.0

def skip(expected: Any, predicted: Any) -> float:
    return -1.0


# Mapping of metric types to comparison functions
METRIC_FUNCTIONS: Dict[Metric, Callable[[Any, Any], float]] = {
    Metric.EQUALITY: compare_equality,
    Metric.LEVENSHTEIN_DISTANCE: compare_levenshtein,
    Metric.DEEP_EQUALITY: compare_deep_equality,
    Metric.STRING_DATE_EQUALITY: compare_string_date,
    Metric.COMPARE_NUMBER: compare_number,
    Metric.SKIP: skip
}
