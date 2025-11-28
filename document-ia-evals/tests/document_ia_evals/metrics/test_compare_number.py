"""
Comprehensive unit tests for COMPARE_NUMBER metric.

This module tests the normalize_number and compare_number functions
that implement number comparison with format normalization.
"""

import pytest

from document_ia_evals.metrics.compare_functions import (
    compare_number,
    normalize_number,
    METRIC_FUNCTIONS,
)
from document_ia_schemas.field_metrics import Metric


class TestNormalizeNumber:
    """Test cases for the normalize_number function."""

    # =========================================================================
    # Basic Integer Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("0", 0.0),
            ("1", 1.0),
            ("123", 123.0),
            ("1234567", 1234567.0),
            ("-1", -1.0),
            ("-123", -123.0),
        ],
        ids=[
            "zero",
            "single_digit",
            "three_digits",
            "seven_digits",
            "negative_single",
            "negative_multi",
        ],
    )
    def test_basic_integers(self, input_value: str, expected: float):
        """Test parsing of basic integer strings."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Basic Decimal Tests (with dot)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("0.0", 0.0),
            ("1.5", 1.5),
            ("12.34", 12.34),
            ("123.456", 123.456),
            (".5", 0.5),
            ("0.123", 0.123),
            ("-1.5", -1.5),
            ("-12.34", -12.34),
        ],
        ids=[
            "zero_decimal",
            "simple_decimal",
            "two_decimal_places",
            "three_decimal_places",
            "leading_dot",
            "leading_zero",
            "negative_decimal",
            "negative_two_decimals",
        ],
    )
    def test_decimal_with_dot(self, input_value: str, expected: float):
        """Test parsing of decimal numbers with dot separator."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Comma as Decimal Separator Tests (European format)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("0,0", 0.0),
            ("1,5", 1.5),
            ("12,34", 12.34),
            ("123,456", 123.456),
            (",5", 0.5),
            ("0,123", 0.123),
            ("-1,5", -1.5),
            ("-12,34", -12.34),
        ],
        ids=[
            "zero_decimal",
            "simple_decimal",
            "two_decimal_places",
            "three_decimal_places",
            "leading_comma",
            "leading_zero",
            "negative_decimal",
            "negative_two_decimals",
        ],
    )
    def test_comma_as_decimal_separator(self, input_value: str, expected: float):
        """Test parsing of numbers with comma as decimal separator (European format)."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Space Handling Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("  123  ", 123.0),
            (" 1 234 567 ", 1234567.0),
            ("1 234", 1234.0),
            ("1 234 567", 1234567.0),
            ("12 345,67", 12345.67),
            ("1 234.56", 1234.56),
            (" - 123 ", -123.0),
        ],
        ids=[
            "leading_trailing_spaces",
            "thousands_with_spaces",
            "simple_space_separator",
            "multiple_space_separators",
            "space_thousands_comma_decimal",
            "space_thousands_dot_decimal",
            "negative_with_spaces",
        ],
    )
    def test_space_handling(self, input_value: str, expected: float):
        """Test that spaces are properly removed from numbers."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Currency Symbol Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("1 200 €", 1200.0),
            ("€1200", 1200.0),
            ("1200€", 1200.0),
            ("$1200", 1200.0),
            ("1200$", 1200.0),
            ("£500", 500.0),
            ("¥10000", 10000.0),
            ("CHF 1'234.56", 1234.56),
            # Note: "$ 1,200.50" would become "1.200.50" (multiple dots) -> None
            # because commas are converted to dots first
            ("$ 1 200,50", 1200.50),  # Using space for thousands + comma for decimal
        ],
        ids=[
            "euro_after_with_spaces",
            "euro_before",
            "euro_after",
            "dollar_before",
            "dollar_after",
            "pound",
            "yen",
            "swiss_franc_apostrophe",
            "dollar_european_format",
        ],
    )
    def test_currency_symbols_removed(self, input_value: str, expected: float):
        """Test that currency symbols are properly stripped."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Percentage and Other Symbols Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("50%", 50.0),
            ("12.5%", 12.5),
            ("100 %", 100.0),
            ("+123", 123.0),
            ("123+", 123.0),
        ],
        ids=[
            "percentage",
            "decimal_percentage",
            "percentage_with_space",
            "plus_sign_before",
            "plus_sign_after",
        ],
    )
    def test_other_symbols_removed(self, input_value: str, expected: float):
        """Test that percentage and other symbols are properly handled."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # None and Empty Handling Tests
    # =========================================================================

    def test_none_returns_none(self):
        """Test that None input returns None."""
        assert normalize_number(None) is None

    @pytest.mark.parametrize(
        "input_value",
        ["", "   ", "\t", "\n"],
        ids=["empty_string", "spaces_only", "tab_only", "newline_only"],
    )
    def test_empty_or_whitespace_returns_none(self, input_value: str):
        """Test that empty or whitespace-only strings return None."""
        result = normalize_number(input_value)
        assert result is None

    # =========================================================================
    # Invalid Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "abc",
            "twelve",
            "1.2.3",  # Multiple dots
            "1,2,3",  # Multiple commas (become multiple dots)
            "1.2.3.4",  # Multiple dots
            "--123",  # Multiple dashes
            "123--",  # Multiple dashes at end
            "1-2-3",  # Multiple dashes
        ],
        ids=[
            "letters_only",
            "word",
            "multiple_dots",
            "multiple_commas",
            "four_dots",
            "double_dash_prefix",
            "double_dash_suffix",
            "dashes_as_separators",
        ],
    )
    def test_invalid_formats_return_none(self, input_value: str):
        """Test that invalid number formats return None."""
        result = normalize_number(input_value)
        assert result is None

    # =========================================================================
    # Edge Cases
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("0", 0.0),
            ("00", 0.0),
            ("000", 0.0),
            ("0.0", 0.0),
            ("0,0", 0.0),
            ("-0", 0.0),
            ("-0.0", 0.0)
        ],
        ids=[
            "zero",
            "double_zero",
            "triple_zero",
            "zero_with_dot",
            "zero_with_comma",
            "negative_zero",
            "negative_zero_decimal"
        ],
    )
    def test_edge_cases(self, input_value: str, expected: float):
        """Test edge cases in number normalization."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Large Numbers Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("1000000", 1000000.0),
            ("1 000 000", 1000000.0),
            ("999999999", 999999999.0),
            ("12345678901234", 12345678901234.0),
        ],
        ids=[
            "million",
            "million_with_spaces",
            "large_number",
            "very_large_number",
        ],
    )
    def test_large_numbers(self, input_value: str, expected: float):
        """Test handling of large numbers."""
        result = normalize_number(input_value)
        assert result == expected

    def test_comma_thousands_becomes_invalid(self):
        """Test that comma as thousands separator creates multiple dots (invalid).
        
        Note: The normalize_number function converts all commas to dots,
        so "1,000,000" becomes "1.000.000" which has multiple dots and is invalid.
        To handle this format, the function would need to be updated.
        """
        result = normalize_number("1,000,000")
        assert result is None  # Multiple dots after comma conversion

    # =========================================================================
    # French/European Number Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("1234,56", 1234.56),
            ("1 234,56", 1234.56),
            ("12 345,67", 12345.67),
            ("123 456,78", 123456.78),
            ("-1 234,56", -1234.56),
        ],
        ids=[
            "simple_european",
            "thousands_space_european",
            "five_digit_european",
            "six_digit_european",
            "negative_european",
        ],
    )
    def test_european_number_format(self, input_value: str, expected: float):
        """Test handling of European number format (space thousands, comma decimal)."""
        result = normalize_number(input_value)
        assert result == expected

    # =========================================================================
    # Real-World Document Values Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            # Tax amounts
            ("12 345 €", 12345.0),
            ("1 234,56 €", 1234.56),
            # Percentages
            ("19,6%", 19.6),
            ("5.5 %", 5.5),
            # Income values
            ("45 000", 45000.0),
            ("45000", 45000.0),
            # Negative values (debts, losses)
            ("-1 234,56", -1234.56),
            ("- 500", -500.0),
        ],
        ids=[
            "tax_amount_integer",
            "tax_amount_decimal",
            "percentage_comma",
            "percentage_dot",
            "income_with_space",
            "income_no_space",
            "negative_debt",
            "negative_with_space",
        ],
    )
    def test_document_values(self, input_value: str, expected: float):
        """Test values commonly found in documents."""
        result = normalize_number(input_value)
        assert result == expected


class TestCompareNumber:
    """Test cases for the compare_number function."""

    # =========================================================================
    # Equality Tests (same values, same or different formats)
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            # Same format
            ("123", "123"),
            ("123.45", "123.45"),
            ("1234,56", "1234,56"),
            # Different formats, same value
            ("123", "123.0"),
            ("123.00", "123"),
            ("1234.56", "1234,56"),
            ("1 234", "1234"),
            ("1 234,56", "1234.56"),
            ("1234 €", "1234"),
            ("€ 1234", "1234.00"),
            # With spaces vs without
            ("1 000", "1000"),
            ("12 345,67", "12345.67"),
            # Currency symbols
            ("100 €", "100"),
            ("$100", "100.00"),
            # Percentage
            ("50%", "50"),
            ("12.5%", "12,5"),
        ],
        ids=[
            "same_integer",
            "same_decimal_dot",
            "same_decimal_comma",
            "int_vs_float",
            "trailing_zeros_vs_int",
            "dot_vs_comma_decimal",
            "space_thousands_vs_no_space",
            "european_vs_standard",
            "euro_suffix_vs_plain",
            "euro_prefix_vs_trailing_zeros",
            "thousands_with_spaces",
            "european_vs_standard_decimal",
            "euro_vs_plain",
            "dollar_vs_trailing_zeros",
            "percentage_vs_int",
            "percentage_dot_vs_comma",
        ],
    )
    def test_equal_numbers_return_1(self, expected: str, predicted: str):
        """Test that equal numbers return 1.0 regardless of format."""
        result = compare_number(expected, predicted)
        assert result == 1.0

    # =========================================================================
    # Inequality Tests (different values)
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("123", "124"),
            ("123.45", "123.46"),
            ("100", "99"),
            ("1000", "100"),
            ("-100", "100"),
            ("100", "-100"),
            ("0", "1"),
            ("0.1", "0.2"),
            ("1234.56", "1234.57"),
        ],
        ids=[
            "different_integers",
            "different_decimals",
            "off_by_one",
            "order_of_magnitude",
            "negative_vs_positive",
            "positive_vs_negative",
            "zero_vs_one",
            "small_decimals",
            "last_decimal_different",
        ],
    )
    def test_different_numbers_return_0(self, expected: str, predicted: str):
        """Test that different numbers return 0.0."""
        result = compare_number(expected, predicted)
        assert result == 0.0

    # =========================================================================
    # None Handling Tests
    # =========================================================================

    def test_both_none_returns_1(self):
        """Test that both None values return 1.0 (both normalize to None, which are equal)."""
        result = compare_number(None, None)
        assert result == 1.0

    def test_expected_none_returns_0(self):
        """Test that None expected with valid predicted returns 0.0."""
        result = compare_number(None, "123")
        assert result == 0.0

    def test_predicted_none_returns_0(self):
        """Test that valid expected with None predicted returns 0.0."""
        result = compare_number("123", None)
        assert result == 0.0

    # =========================================================================
    # Invalid Value Handling Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("abc", "123"),  # Invalid expected
            ("123", "abc"),  # Invalid predicted
            ("1.2.3", "123"),  # Multiple dots in expected
            ("123", "1,2,3"),  # Multiple commas in predicted
        ],
        ids=[
            "invalid_expected",
            "invalid_predicted",
            "multiple_dots_expected",
            "multiple_commas_predicted",
        ],
    )
    def test_invalid_handling(self, expected: str, predicted: str):
        """Test handling of invalid number values."""
        result = compare_number(expected, predicted)
        assert result == 0.0

    # =========================================================================
    # Empty String Handling Tests
    # =========================================================================

    def test_both_empty_returns_1(self):
        """Test that both empty strings return 1.0 (both normalize to None)."""
        result = compare_number("", "")
        assert result == 1.0

    def test_empty_vs_valid_returns_0(self):
        """Test that empty string vs valid number returns 0.0."""
        assert compare_number("", "123") == 0.0
        assert compare_number("123", "") == 0.0

    # =========================================================================
    # Floating Point Precision Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted,should_match",
        [
            ("0.1", "0.1", True),
            ("0.10", "0.1", True),
            ("0.100", "0.1", True),
            ("1.0", "1.00", True),
            ("1.23456789", "1.23456789", True),
        ],
        ids=[
            "same_decimal",
            "trailing_zero",
            "two_trailing_zeros",
            "integer_with_zeros",
            "many_decimals",
        ],
    )
    def test_floating_point_precision(
        self, expected: str, predicted: str, should_match: bool
    ):
        """Test floating point comparison precision."""
        result = compare_number(expected, predicted)
        if should_match:
            assert result == 1.0
        else:
            assert result == 0.0

    # =========================================================================
    # Numeric Type Input Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            (123, "123"),
            ("123", 123),
            (123.45, "123.45"),
            ("123,45", 123.45),
            (1000, "1 000"),
            (-100, "-100"),
        ],
        ids=[
            "int_vs_string",
            "string_vs_int",
            "float_vs_string",
            "comma_string_vs_float",
            "int_vs_space_string",
            "negative_int_vs_string",
        ],
    )
    def test_mixed_types(self, expected, predicted):
        """Test comparison with mixed types (int, float, string)."""
        result = compare_number(expected, predicted)
        assert result == 1.0

    # =========================================================================
    # Edge Cases
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted,should_match",
        [
            ("0", "0.0", True),
            ("-0", "0", True),
            ("-0.0", "0.0", True),
            ("000", "0", True),
            ("0.0", "0,0", True),
        ],
        ids=[
            "zero_int_vs_float",
            "negative_zero_vs_zero",
            "negative_zero_float_vs_zero_float",
            "leading_zeros_vs_zero",
            "zero_dot_vs_comma",
        ],
    )
    def test_zero_edge_cases(self, expected: str, predicted: str, should_match: bool):
        """Test edge cases involving zero."""
        result = compare_number(expected, predicted)
        if should_match:
            assert result == 1.0
        else:
            assert result == 0.0


class TestMetricFunctionsMapping:
    """Test that COMPARE_NUMBER is properly mapped in METRIC_FUNCTIONS."""

    def test_compare_number_in_metric_functions(self):
        """Test that COMPARE_NUMBER maps to compare_number."""
        assert Metric.COMPARE_NUMBER in METRIC_FUNCTIONS
        assert METRIC_FUNCTIONS[Metric.COMPARE_NUMBER] == compare_number

    def test_metric_function_callable(self):
        """Test that the mapped function is callable and works correctly."""
        func = METRIC_FUNCTIONS[Metric.COMPARE_NUMBER]
        assert callable(func)
        assert func("1234.56", "1 234,56") == 1.0
        assert func("100", "200") == 0.0


class TestRealWorldScenarios:
    """Test real-world scenarios commonly encountered in document processing."""

    @pytest.mark.parametrize(
        "expected,predicted,should_match",
        [
            # Tax documents (avis d'imposition)
            ("12 345", "12345", True),
            ("12 345,67", "12345.67", True),
            ("45 000 €", "45000", True),
            # Different OCR outputs for same value
            ("1234", "1 234", True),
            ("1234,56", "1234.56", True),
            # Wrong values should fail
            ("12345", "12346", False),
            ("100,00", "100,01", False),
            # Negative amounts
            ("-1 234,56 €", "-1234.56", True),
            # Percentages in tax documents
            ("19,6%", "19.6", True),
            ("5,5 %", "5.5", True),
            # Income values with different formats
            ("50 000", "50000", True),
            ("50 000,00 €", "50000", True),
        ],
        ids=[
            "tax_integer_space_vs_no_space",
            "tax_decimal_european_vs_standard",
            "tax_with_euro_vs_plain",
            "ocr_space_variant",
            "ocr_comma_vs_dot",
            "wrong_integer",
            "wrong_decimal",
            "negative_amount",
            "vat_rate_comma",
            "vat_rate_space",
            "income_with_space",
            "income_full_format",
        ],
    )
    def test_document_processing_scenarios(
        self, expected: str, predicted: str, should_match: bool
    ):
        """Test scenarios commonly encountered in document processing."""
        result = compare_number(expected, predicted)
        if should_match:
            assert result == 1.0
        else:
            assert result == 0.0

    @pytest.mark.parametrize(
        "expected,predicted,should_match",
        [
            # Salary values
            ("2 500,00", "2500", True),
            ("2 500,00 €", "2500.00", True),
            # Social security numbers (treated as numbers)
            ("1234567890123", "1234567890123", True),
            # Reference numbers
            ("123456789", "123456789", True),
        ],
        ids=[
            "salary_with_decimals",
            "salary_with_euro",
            "large_number_id",
            "reference_number",
        ],
    )
    def test_payslip_scenarios(
        self, expected: str, predicted: str, should_match: bool
    ):
        """Test scenarios from payslip (bulletin de salaire) processing."""
        result = compare_number(expected, predicted)
        if should_match:
            assert result == 1.0
        else:
            assert result == 0.0

