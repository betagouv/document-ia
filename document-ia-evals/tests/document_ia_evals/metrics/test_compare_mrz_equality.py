"""Unit tests for the MRZ_EQUALITY metric."""

import pytest

from document_ia_evals.metrics.compare_functions import (
    METRIC_FUNCTIONS,
    compare_mrz_equality,
    normalize_mrz,
)
from document_ia_schemas.field_metrics import Metric


class TestNormalizeMrz:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("P<UTOERIKSSON<<ANNA<MARIA", "PUTOERIKSSONANNAMARIA"),
            ("p<uto\neriksson << anna maria", "PUTOERIKSSONANNAMARIA"),
            ("  P<UTO  ", "PUTO"),
            (None, ""),
        ],
    )
    def test_removes_filler_and_formatting(self, value, expected):
        assert normalize_mrz(value) == expected


class TestCompareMrzEquality:
    @pytest.mark.parametrize(
        "expected,predicted",
        [
            (
                "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<<",
                "putoeriksson anna maria",
            ),
            (
                "P<UTOERIKSSON<<ANNA<MARIA\n<<<<<<<<<<<<<<<<<<<<",
                "P<UTOERIKSSONANNAMARIA<<<<<<<<<<<<<<<<<<<<",
            ),
            ("", None),
        ],
    )
    def test_returns_one_when_mrz_values_are_equal_after_normalization(
        self, expected, predicted
    ):
        assert compare_mrz_equality(expected, predicted) == 1.0

    def test_returns_zero_when_significant_character_differs(self):
        expected = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<<"
        predicted = "P<UTOERIKSSON<<ANNE<MARIA<<<<<<<<<<<<<<<<<<<<"

        assert compare_mrz_equality(expected, predicted) == 0.0

    def test_metric_exists_in_mapping(self):
        assert Metric.MRZ_EQUALITY in METRIC_FUNCTIONS
        assert METRIC_FUNCTIONS[Metric.MRZ_EQUALITY] == compare_mrz_equality
