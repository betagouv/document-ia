"""Unit tests for TOKEN_SET_EQUALITY metric."""

import pytest

from document_ia_evals.metrics.compare_functions import (
    METRIC_FUNCTIONS,
    compare_token_set_equality,
)
from document_ia_schemas.field_metrics import Metric


class TestCompareTokenSetEquality:
    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("prenom nom", "nom prenom"),
            ("jean-pierre dupont", "dupont jean pierre"),
            ("Élodie Martin", "martin elodie"),
            ("nom   prenom", "prenom nom"),
            ("nom prenom", "nom prenom"),
        ],
    )
    def test_returns_one_for_same_tokens_in_any_order(self, expected: str, predicted: str):
        assert compare_token_set_equality(expected, predicted) == 1.0

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("prenom nom", "prenom"),
            ("prenom nom", "prenom nom junior"),
            ("jean paul", "jean pierre"),
            ("", "nom"),
            (None, "nom"),
        ],
    )
    def test_returns_zero_when_token_sets_differ(self, expected, predicted):
        assert compare_token_set_equality(expected, predicted) == 0.0

    def test_returns_one_when_both_empty_after_normalization(self):
        assert compare_token_set_equality("", "") == 1.0


class TestMetricFunctionsMapping:
    def test_metric_exists_in_mapping(self):
        assert Metric.TOKEN_SET_EQUALITY in METRIC_FUNCTIONS
        assert METRIC_FUNCTIONS[Metric.TOKEN_SET_EQUALITY] == compare_token_set_equality
