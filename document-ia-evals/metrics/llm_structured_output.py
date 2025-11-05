"""LLM Structured Output metric for comparing JSON outputs."""

import json
import re
import numpy as np
from typing import Tuple, Dict, Any
from deepdiff import DeepDiff
from metrics import metric_registry


def parse_json_from_response(response: str | dict) -> dict | None:
    """
    Extract and parse JSON from an LLM response.
    Handles responses that may contain extra text or markdown formatting.
    """
    if isinstance(response, dict):
        return response

    # Try to parse the response directly
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON in the response using regex
    # Look for content between curly braces
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON in markdown code blocks
    code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass
    
    return None


def count_total_values(data):
    """
    Recursively count all values in a nested data structure.
    This includes:
    - All leaf values (strings, numbers, booleans, None)
    - Each item in arrays/lists
    - Each key-value pair in objects/dictionaries
    """
    if data is None:
        return 1
    elif isinstance(data, (str, int, float, bool)):
        return 1
    elif isinstance(data, list):
        return sum(count_total_values(item) for item in data)
    elif isinstance(data, dict):
        return sum(count_total_values(value) for value in data.values())
    else:
        return 1  # For any other type


def calculate_similarity_score(expected_data, extracted_data, diff):
    """
    Calculate similarity score based on total number of values rather than just keys.
    
    Args:
        expected_data: Ground truth data structure
        extracted_data: LLM extracted data structure  
        diff: DeepDiff result between expected and extracted data
    
    Returns:
        float: Score between 0 and 1, where 1 is perfect match
    """
    if expected_data is None and extracted_data is None:
        return 1.0
    if expected_data is None or extracted_data is None:
        return 0.0
    
    if not diff:
        return 1.0
    
    # Count total values in expected data
    total_expected_values = count_total_values(expected_data)
    
    # Count the number of differences
    diff_count = 0
    
    # Count value changes
    diff_count += len(diff.get('values_changed', {}))
    
    # Count type changes
    diff_count += len(diff.get('type_changes', {}))
    
    # Count missing items (in expected but not in extracted)
    if 'dictionary_item_removed' in diff:
        for removed_path in diff['dictionary_item_removed']:
            diff_count += 1
    
    if 'iterable_item_removed' in diff:
        for removed_item in diff['iterable_item_removed'].values():
            diff_count += count_total_values(removed_item)
    
    # Count extra items (in extracted but not in expected)  
    if 'dictionary_item_added' in diff:
        for added_path in diff['dictionary_item_added']:
            diff_count += 1
    
    if 'iterable_item_added' in diff:
        for added_item in diff['iterable_item_added'].values():
            diff_count += count_total_values(added_item)
    
    # Calculate score
    if total_expected_values == 0:
        return 1.0 if diff_count == 0 else 0.0
    
    score = max(0.0, 1.0 - (diff_count / total_expected_values))
    return score


def calculate_field_level_scores(expected_data, extracted_data):
    """
    Calculate similarity scores for each top-level key in the JSON structure.
    
    Args:
        expected_data: Ground truth data structure (dict)
        extracted_data: LLM extracted data structure (dict)
    
    Returns:
        dict: Dictionary mapping each key to its similarity score
    """
    if not isinstance(expected_data, dict) or not isinstance(extracted_data, dict):
        return {}
    
    key_scores = {}
    all_keys = set(expected_data.keys()) | set(extracted_data.keys())
    
    for key in all_keys:
        expected_value = expected_data.get(key)
        extracted_value = extracted_data.get(key)
        
        # Calculate diff for this specific key
        key_diff = DeepDiff(expected_value, extracted_value, ignore_order=True)
        
        # Calculate score for this key
        key_score = calculate_similarity_score(expected_value, extracted_value, key_diff)
        key_scores[key] = key_score
    
    return key_scores


@metric_registry.register(
    name="llm_structured_output",
    description="Compare JSON LLM output with provided ground truth JSON and compute an overall score and key level accuracy scores",
    metric_type="json_comparison",
    require=["prediction", "ground_truth"],
)
def llm_structured_output_metric(prediction: Any, ground_truth: Any, **kwargs) -> Tuple[float, str, Any]:
    """
    Compare predicted JSON output with ground truth.
    
    Args:
        prediction: The predicted output (can be JSON string or dict)
        ground_truth: The ground truth output (can be JSON string or dict)
        **kwargs: Additional parameters (unused)
    
    Returns:
        Tuple of (score, observation_json, output):
            - score: Overall similarity score (0.0 to 1.0)
            - observation_json: JSON string with detailed results
            - output: The prediction for reference
    """
    # Parse the expected output (ground truth)
    expected_data = parse_json_from_response(ground_truth)
    if expected_data is None:
        error_obs = {
            "score": 0.0,
            "error": "Failed to parse ground truth JSON",
            "ground_truth_raw": str(ground_truth)[:500]
        }
        return 0.0, json.dumps(error_obs, indent=2), prediction
    
    # Parse the prediction
    extracted_data = parse_json_from_response(prediction)
    if extracted_data is None:
        observation = {
            "score": 0.0,
            "error": "Failed to extract valid JSON from prediction",
            "prediction_raw": str(prediction)[:500],
            "expected_data": expected_data
        }
        return 0.0, json.dumps(observation, indent=2), prediction
    
    # Calculate similarity scores
    diff = DeepDiff(expected_data, extracted_data, ignore_order=True)
    field_scores = calculate_field_level_scores(expected_data, extracted_data)
    
    # Calculate overall score
    overall_score = sum(field_scores.values()) / len(field_scores) if field_scores else 0.0

    # Build detailed observation
    observation = {
        "score": overall_score,
        "extracted_data": extracted_data,
        "expected_data": expected_data,
        "field_scores": field_scores,
    }
    
    # Add diff details if there are differences
    if diff:
        observation["differences"] = str(diff)[:1000]  # Limit diff size
    
    return overall_score, json.dumps(observation, indent=2), prediction


def render_results(experiment_results: Dict[str, Any]) -> None:
    """
    Render the results of the llm_structured_output metric.
    
    Args:
        experiment_results: Dictionary containing experiment data with observations
    """
    import streamlit as st
    import pandas as pd
    from collections import defaultdict
    
    st.subheader("📝 Structured Output Analysis")
    
    # Collect data
    all_field_names = set()
    model_data = {}
    
    observations = experiment_results.get("observations", [])
    
    global_scores = []
    field_scores_by_name = defaultdict(list)
    errors_count = 0
    
    for obs in observations:
        if obs.get("observation"):
            try:
                obs_data = json.loads(obs["observation"])
                if "score" in obs_data:
                    global_scores.append(obs_data["score"])
                field_scores = obs_data.get("field_scores", {})
                for field_name, field_score in field_scores.items():
                    if isinstance(field_score, (int, float)):
                        all_field_names.add(field_name)
                        field_scores_by_name[field_name].append(field_score)
                if "error" in obs_data:
                    errors_count += 1
            except (json.JSONDecodeError, TypeError):
                errors_count += 1
    
    # Display summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Overall Score", f"{np.mean(global_scores):.3f}" if global_scores else "N/A")
    with col2:
        st.metric("Total Items", len(observations))
    with col3:
        st.metric("Errors", errors_count)
    
    # Display field scores
    if field_scores_by_name:
        st.write("**Field Scores**")
        field_data = []
        for field_name in sorted(all_field_names):
            scores = field_scores_by_name[field_name]
            field_data.append({
                "Field": field_name,
                "Mean Score": f"{np.mean(scores):.3f}",
                "Min Score": f"{min(scores):.3f}",
                "Max Score": f"{max(scores):.3f}",
                "Count": len(scores)
            })
        
        field_df = pd.DataFrame(field_data)
        st.dataframe(field_df, use_container_width=True, hide_index=True)
    
    # Show error details if any
    if errors_count > 0:
        with st.expander(f"Error Details ({errors_count} errors)", expanded=False):
            for idx, obs in enumerate(observations):
                if obs.get("observation"):
                    try:
                        obs_data = json.loads(obs["observation"])
                        if "error" in obs_data:
                            st.error(f"**Item {idx + 1}:** {obs_data['error']}")
                    except:
                        pass