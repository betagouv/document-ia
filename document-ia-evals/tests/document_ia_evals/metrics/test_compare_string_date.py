"""
Comprehensive unit tests for STRING_DATE_EQUALITY metric.

This module tests the normalize_string_date and compare_string_date functions
that implement date comparison with format normalization.
"""

from datetime import date

import pytest

from document_ia_evals.metrics.compare_functions import (
    compare_string_date,
    normalize_string_date,
    METRIC_FUNCTIONS,
)
from document_ia_schemas.field_metrics import Metric


class TestNormalizeStringDate:
    """Test cases for the normalize_string_date function."""

    # =========================================================================
    # DD/MM/YYYY Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("01/01/2024", date(2024, 1, 1)),
            ("31/12/2023", date(2023, 12, 31)),
            ("15/06/2020", date(2020, 6, 15)),
            ("28/02/2024", date(2024, 2, 28)),  # Leap year
            ("29/02/2024", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_dd_slash_mm_slash_yyyy_format(self, input_value: str, expected: date):
        """Test parsing of DD/MM/YYYY format."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # DD-MM-YYYY Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("01-01-2024", date(2024, 1, 1)),
            ("31-12-2023", date(2023, 12, 31)),
            ("15-06-2020", date(2020, 6, 15)),
            ("28-02-2024", date(2024, 2, 28)),  # Leap year
            ("29-02-2024", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_dd_dash_mm_dash_yyyy_format(self, input_value: str, expected: date):
        """Test parsing of DD-MM-YYYY format."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # DDMMYYYY Format Tests (8 digits, no separator)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("01012024", date(2024, 1, 1)),
            ("31122023", date(2023, 12, 31)),
            ("15062020", date(2020, 6, 15)),
            ("28022024", date(2024, 2, 28)),
            ("29022024", date(2024, 2, 29)),  # Leap year
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_ddmmyyyy_format(self, input_value: str, expected: date):
        """Test parsing of DDMMYYYY format (8 consecutive digits)."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # ISO Format Tests (YYYY-MM-DD)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("2024-01-01", date(2024, 1, 1)),
            ("2023-12-31", date(2023, 12, 31)),
            ("2020-06-15", date(2020, 6, 15)),
            ("2024-02-28", date(2024, 2, 28)),  # Leap year
            ("2024-02-29", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_yyyy_dash_mm_dash_dd_format(self, input_value: str, expected: date):
        """Test parsing of YYYY-MM-DD (ISO) format."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # YYYY/MM/DD Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("2024/01/01", date(2024, 1, 1)),
            ("2023/12/31", date(2023, 12, 31)),
            ("2020/06/15", date(2020, 6, 15)),
            ("2024/02/28", date(2024, 2, 28)),  # Leap year
            ("2024/02/29", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_yyyy_slash_mm_slash_dd_format(self, input_value: str, expected: date):
        """Test parsing of YYYY/MM/DD format."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # YYYYMMDD Format Tests (8 digits, year first)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("20240101", date(2024, 1, 1)),
            ("20231231", date(2023, 12, 31)),
            ("20200615", date(2020, 6, 15)),
            ("20240228", date(2024, 2, 28)),  # Leap year
            ("20240229", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_yyyymmdd_format(self, input_value: str, expected: date):
        """Test parsing of YYYYMMDD format (8 consecutive digits, year first)."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # DD.MM.YYYY Format Tests (European with dot separator)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("01.01.2024", date(2024, 1, 1)),
            ("31.12.2023", date(2023, 12, 31)),
            ("15.06.2020", date(2020, 6, 15)),
            ("28.02.2024", date(2024, 2, 28)),  # Leap year
            ("29.02.2024", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_dd_dot_mm_dot_yyyy_format(self, input_value: str, expected: date):
        """Test parsing of DD.MM.YYYY format (European with dot separator)."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # YYYY.MM.DD Format Tests (ISO with dot separator)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("2024.01.01", date(2024, 1, 1)),
            ("2023.12.31", date(2023, 12, 31)),
            ("2020.06.15", date(2020, 6, 15)),
            ("2024.02.28", date(2024, 2, 28)),  # Leap year
            ("2024.02.29", date(2024, 2, 29)),  # Leap year - Feb 29
        ],
        ids=[
            "new_year_2024",
            "new_years_eve_2023",
            "mid_year_2020",
            "feb_28_leap_year",
            "feb_29_leap_year",
        ],
    )
    def test_yyyy_dot_mm_dot_dd_format(self, input_value: str, expected: date):
        """Test parsing of YYYY.MM.DD format (ISO with dot separator)."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # Whitespace Handling Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("  01/01/2024  ", date(2024, 1, 1)),
            (" 01012024 ", date(2024, 1, 1)),
            ("01/01/2024\n", date(2024, 1, 1)),
            ("\t15/06/2020\t", date(2020, 6, 15)),
        ],
        ids=[
            "leading_trailing_spaces_slash_format",
            "leading_trailing_spaces_digit_format",
            "trailing_newline",
            "tabs",
        ],
    )
    def test_whitespace_trimming(self, input_value: str, expected: date):
        """Test that whitespace is properly stripped before parsing."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # None and Empty Handling Tests
    # =========================================================================

    def test_none_returns_none(self):
        """Test that None input returns None."""
        assert normalize_string_date(None) is None

    @pytest.mark.parametrize(
        "input_value",
        ["", "   ", "\t", "\n"],
        ids=["empty_string", "spaces_only", "tab_only", "newline_only"],
    )
    def test_empty_or_whitespace_returns_none(self, input_value: str):
        """Test that empty or whitespace-only strings are handled."""
        # After strip, these become empty and should fail parsing
        result = normalize_string_date(input_value)
        # Empty strings don't match any format, so they should return None
        assert result is None

    # =========================================================================
    # Single Digit Day/Month Tests (Python strptime accepts these)
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("1/1/2024", date(2024, 1, 1)),  # Single digit day and month
            ("1/01/2024", date(2024, 1, 1)),  # Single digit day
            ("01/1/2024", date(2024, 1, 1)),  # Single digit month
            ("9/12/2023", date(2023, 12, 9)),  # Single digit day
            ("25/6/2020", date(2020, 6, 25)),  # Single digit month
        ],
        ids=[
            "single_digit_day_month",
            "single_digit_day",
            "single_digit_month",
            "single_digit_day_december",
            "single_digit_month_june",
        ],
    )
    def test_single_digit_formats_accepted(self, input_value: str, expected: date):
        """Test that Python's strptime accepts single-digit day/month in DD/MM/YYYY format."""
        result = normalize_string_date(input_value)
        assert result == expected

    # =========================================================================
    # Invalid Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "January 1, 2024",  # Written format
            "1 Jan 2024",  # Short written format
            "01 Jan 2024",  # Short written format with leading zero
            "2024 Jan 01",  # Year first written format
        ],
        ids=[
            "written_format",
            "short_written_format",
            "short_written_leading_zero",
            "year_first_written",
        ],
    )
    def test_unsupported_formats_return_none(self, input_value: str):
        """Test that unsupported date formats return None."""
        result = normalize_string_date(input_value)
        assert result is None

    # =========================================================================
    # Invalid Date Value Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "32/01/2024",  # Day > 31
            "00/01/2024",  # Day = 0
            "01/13/2024",  # Month > 12
            "01/00/2024",  # Month = 0
            "29/02/2023",  # Feb 29 in non-leap year
            "31/04/2024",  # April has 30 days
            "31/06/2024",  # June has 30 days
            "31/09/2024",  # September has 30 days
            "31/11/2024",  # November has 30 days
        ],
        ids=[
            "day_32",
            "day_0",
            "month_13",
            "month_0",
            "feb_29_non_leap_year",
            "april_31",
            "june_31",
            "september_31",
            "november_31",
        ],
    )
    def test_invalid_date_values_return_none(self, input_value: str):
        """Test that invalid date values return None."""
        result = normalize_string_date(input_value)
        assert result is None

    # =========================================================================
    # Invalid 8-Digit Format Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "3201024",  # Too short (7 digits)
            "010120241",  # Too long (9 digits)
            "abcdefgh",  # Non-digits, 8 chars
            "01a12024",  # Mixed chars/digits
            "29022023",  # Feb 29 in non-leap year (DDMMYYYY format)
            "20230229",  # Feb 29 in non-leap year (YYYYMMDD format)
        ],
        ids=[
            "7_digits",
            "9_digits",
            "letters_8_chars",
            "mixed_chars_digits",
            "feb_29_non_leap_year_ddmmyyyy",
            "feb_29_non_leap_year_yyyymmdd",
        ],
    )
    def test_invalid_8digit_formats(self, input_value: str):
        """Test that invalid 8-character patterns are handled."""
        result = normalize_string_date(input_value)
        assert result is None

    # =========================================================================
    # Invalid ISO Date Value Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "2024-01-32",  # Day > 31 (ISO)
            "2024-00-01",  # Month = 0 (ISO)
            "2024-13-01",  # Month > 12 (ISO)
            "2023-02-29",  # Feb 29 in non-leap year (ISO)
            "2024-04-31",  # April has 30 days (ISO)
            "2024/01/32",  # Day > 31 (YYYY/MM/DD)
            "2024/02/30",  # Feb 30 (YYYY/MM/DD)
        ],
        ids=[
            "iso_day_32",
            "iso_month_0",
            "iso_month_13",
            "iso_feb_29_non_leap_year",
            "iso_april_31",
            "slash_iso_day_32",
            "slash_iso_feb_30",
        ],
    )
    def test_invalid_iso_date_values_return_none(self, input_value: str):
        """Test that invalid ISO date values return None."""
        result = normalize_string_date(input_value)
        assert result is None

    # =========================================================================
    # Invalid Dot-Separated Date Value Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value",
        [
            "32.01.2024",  # Day > 31 (DD.MM.YYYY)
            "00.01.2024",  # Day = 0 (DD.MM.YYYY)
            "01.13.2024",  # Month > 12 (DD.MM.YYYY)
            "29.02.2023",  # Feb 29 in non-leap year (DD.MM.YYYY)
            "31.04.2024",  # April has 30 days (DD.MM.YYYY)
            "2024.01.32",  # Day > 31 (YYYY.MM.DD)
            "2024.13.01",  # Month > 12 (YYYY.MM.DD)
            "2023.02.29",  # Feb 29 in non-leap year (YYYY.MM.DD)
        ],
        ids=[
            "dd_dot_day_32",
            "dd_dot_day_0",
            "dd_dot_month_13",
            "dd_dot_feb_29_non_leap_year",
            "dd_dot_april_31",
            "yyyy_dot_day_32",
            "yyyy_dot_month_13",
            "yyyy_dot_feb_29_non_leap_year",
        ],
    )
    def test_invalid_dot_date_values_return_none(self, input_value: str):
        """Test that invalid dot-separated date values return None."""
        result = normalize_string_date(input_value)
        assert result is None

    # =========================================================================
    # Type Coercion Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            (1012024, None),  # Integer missing leading zero - becomes "1012024" (7 digits)
            (1012024.0, None),  # Float - becomes "1012024.0"
        ],
        ids=["integer_no_leading_zero", "float"],
    )
    def test_non_string_types(self, input_value, expected):
        """Test handling of non-string types that get converted to strings."""
        result = normalize_string_date(input_value)
        assert result == expected


class TestCompareStringDate:
    """Test cases for the compare_string_date function."""

    # =========================================================================
    # Equality Tests (same dates, same or different formats)
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            # Same format tests
            ("01/01/2024", "01/01/2024"),  # Same format DD/MM/YYYY
            ("01012024", "01012024"),  # Same format DDMMYYYY
            ("2024-01-01", "2024-01-01"),  # Same format YYYY-MM-DD (ISO)
            ("2024/01/01", "2024/01/01"),  # Same format YYYY/MM/DD
            ("20240101", "20240101"),  # Same format YYYYMMDD
            ("01.01.2024", "01.01.2024"),  # Same format DD.MM.YYYY
            ("2024.01.01", "2024.01.01"),  # Same format YYYY.MM.DD
            # European formats cross-format
            ("01/01/2024", "01012024"),  # DD/MM/YYYY vs DDMMYYYY
            ("01012024", "01/01/2024"),  # DDMMYYYY vs DD/MM/YYYY
            ("31/12/2023", "31122023"),  # Cross-format year end
            ("29/02/2024", "29022024"),  # Leap year cross-format
            ("01-01-2024", "01012024"),  # DD-MM-YYYY vs DDMMYYYY
            ("01012024", "01-01-2024"),  # DDMMYYYY vs DD-MM-YYYY
            ("01.01.2024", "01012024"),  # DD.MM.YYYY vs DDMMYYYY
            ("01012024", "01.01.2024"),  # DDMMYYYY vs DD.MM.YYYY
            ("01/01/2024", "01.01.2024"),  # DD/MM/YYYY vs DD.MM.YYYY
            ("01-01-2024", "01.01.2024"),  # DD-MM-YYYY vs DD.MM.YYYY
            # ISO formats cross-format
            ("2024-01-01", "20240101"),  # YYYY-MM-DD vs YYYYMMDD
            ("20240101", "2024-01-01"),  # YYYYMMDD vs YYYY-MM-DD
            ("2024/01/01", "20240101"),  # YYYY/MM/DD vs YYYYMMDD
            ("2024-01-01", "2024/01/01"),  # YYYY-MM-DD vs YYYY/MM/DD
            ("2024.01.01", "20240101"),  # YYYY.MM.DD vs YYYYMMDD
            ("20240101", "2024.01.01"),  # YYYYMMDD vs YYYY.MM.DD
            ("2024-01-01", "2024.01.01"),  # YYYY-MM-DD vs YYYY.MM.DD
            ("2024/01/01", "2024.01.01"),  # YYYY/MM/DD vs YYYY.MM.DD
            # European vs ISO cross-format
            ("01/01/2024", "2024-01-01"),  # DD/MM/YYYY vs YYYY-MM-DD
            ("2024-01-01", "01/01/2024"),  # YYYY-MM-DD vs DD/MM/YYYY
            ("01012024", "20240101"),  # DDMMYYYY vs YYYYMMDD
            ("20240101", "01012024"),  # YYYYMMDD vs DDMMYYYY
            ("15/06/2020", "2020-06-15"),  # DD/MM/YYYY vs YYYY-MM-DD mid-year
            ("31-12-2023", "2023-12-31"),  # DD-MM-YYYY vs YYYY-MM-DD year end
            ("01.01.2024", "2024.01.01"),  # DD.MM.YYYY vs YYYY.MM.DD
            ("15.06.2020", "2020.06.15"),  # DD.MM.YYYY vs YYYY.MM.DD mid-year
            ("01.01.2024", "2024-01-01"),  # DD.MM.YYYY vs YYYY-MM-DD
            ("2024.01.01", "01/01/2024"),  # YYYY.MM.DD vs DD/MM/YYYY
        ],
        ids=[
            "same_dd_slash_mm_slash_yyyy",
            "same_ddmmyyyy",
            "same_yyyy_dash_mm_dash_dd",
            "same_yyyy_slash_mm_slash_dd",
            "same_yyyymmdd",
            "same_dd_dot_mm_dot_yyyy",
            "same_yyyy_dot_mm_dot_dd",
            "dd_slash_vs_ddmmyyyy",
            "ddmmyyyy_vs_dd_slash",
            "year_end_cross_format",
            "leap_year_cross_format",
            "dd_dash_mm_dash_yyyy_vs_ddmmyyyy",
            "ddmmyyyy_vs_dd_dash_mm_dash_yyyy",
            "dd_dot_vs_ddmmyyyy",
            "ddmmyyyy_vs_dd_dot",
            "dd_slash_vs_dd_dot",
            "dd_dash_vs_dd_dot",
            "iso_dash_vs_yyyymmdd",
            "yyyymmdd_vs_iso_dash",
            "iso_slash_vs_yyyymmdd",
            "iso_dash_vs_iso_slash",
            "iso_dot_vs_yyyymmdd",
            "yyyymmdd_vs_iso_dot",
            "iso_dash_vs_iso_dot",
            "iso_slash_vs_iso_dot",
            "european_vs_iso",
            "iso_vs_european",
            "ddmmyyyy_vs_yyyymmdd",
            "yyyymmdd_vs_ddmmyyyy",
            "european_vs_iso_mid_year",
            "european_dash_vs_iso_year_end",
            "dd_dot_vs_yyyy_dot",
            "dd_dot_vs_yyyy_dot_mid_year",
            "dd_dot_vs_iso_dash",
            "yyyy_dot_vs_dd_slash",
        ],
    )
    def test_equal_dates_return_1(self, expected: str, predicted: str):
        """Test that equal dates return 1.0 regardless of format."""
        result = compare_string_date(expected, predicted)
        assert result == 1.0

    # =========================================================================
    # Inequality Tests (different dates)
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            # European format differences
            ("01/01/2024", "02/01/2024"),  # Different day
            ("01/01/2024", "01/02/2024"),  # Different month
            ("01/01/2024", "01/01/2023"),  # Different year
            ("01012024", "02012024"),  # Different day (DDMMYYYY)
            ("15/06/2020", "16062020"),  # Cross-format, different day
            ("31/12/2023", "01/01/2024"),  # One day apart
            ("01-01-2024", "02-01-2024"),  # Different day (DD-MM-YYYY)
            # ISO format differences
            ("2024-01-01", "2024-01-02"),  # Different day (ISO)
            ("2024-01-01", "2024-02-01"),  # Different month (ISO)
            ("2024-01-01", "2023-01-01"),  # Different year (ISO)
            ("20240101", "20240102"),  # Different day (YYYYMMDD)
            # Cross-format European vs ISO differences
            ("01/01/2024", "2024-01-02"),  # European vs ISO, different day
            ("2024-06-15", "16/06/2024"),  # ISO vs European, different day
            # Dot separator format differences
            ("01.01.2024", "02.01.2024"),  # Different day (DD.MM.YYYY)
            ("01.01.2024", "01.02.2024"),  # Different month (DD.MM.YYYY)
            ("2024.01.01", "2024.01.02"),  # Different day (YYYY.MM.DD)
            ("01.01.2024", "2024.01.02"),  # DD.MM.YYYY vs YYYY.MM.DD different day
            ("01.01.2024", "02/01/2024"),  # DD.MM.YYYY vs DD/MM/YYYY different day
        ],
        ids=[
            "different_day",
            "different_month",
            "different_year",
            "different_day_ddmmyyyy",
            "cross_format_different_day",
            "one_day_apart",
            "different_day_dd_dash_mm_dash_yyyy",
            "different_day_iso",
            "different_month_iso",
            "different_year_iso",
            "different_day_yyyymmdd",
            "european_vs_iso_different_day",
            "iso_vs_european_different_day",
            "different_day_dd_dot",
            "different_month_dd_dot",
            "different_day_yyyy_dot",
            "dd_dot_vs_yyyy_dot_different_day",
            "dd_dot_vs_dd_slash_different_day",
        ],
    )
    def test_different_dates_return_0(self, expected: str, predicted: str):
        """Test that different dates return 0.0."""
        result = compare_string_date(expected, predicted)
        assert result == 0.0

    # =========================================================================
    # None Handling Tests
    # =========================================================================

    def test_both_none_returns_0(self):
        """Test that both None values return 0.0 (not valid dates)."""
        result = compare_string_date(None, None)
        assert result == 0.0

    def test_expected_none_returns_0(self):
        """Test that None expected with valid predicted returns 0.0."""
        result = compare_string_date(None, "01/01/2024")
        assert result == 0.0

    def test_predicted_none_returns_0(self):
        """Test that valid expected with None predicted returns 0.0."""
        result = compare_string_date("01/01/2024", None)
        assert result == 0.0

    # =========================================================================
    # Invalid Date Handling Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("invalid", "01/01/2024"),  # Invalid expected
            ("01/01/2024", "invalid"),  # Invalid predicted
            ("invalid", "invalid"),  # Both invalid
            ("32/01/2024", "01/01/2024"),  # Invalid day in expected
            ("01/01/2024", "01/13/2024"),  # Invalid month in predicted
            ("not-a-date", "also-not-a-date"),  # Both garbage
        ],
        ids=[
            "invalid_expected",
            "invalid_predicted",
            "both_invalid",
            "invalid_day_expected",
            "invalid_month_predicted",
            "both_garbage",
        ],
    )
    def test_invalid_dates_return_0(self, expected: str, predicted: str):
        """Test that invalid date values return 0.0."""
        result = compare_string_date(expected, predicted)
        assert result == 0.0

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_whitespace_handling_in_comparison(self):
        """Test that whitespace is handled in both expected and predicted."""
        result = compare_string_date("  01/01/2024  ", "01012024  ")
        assert result == 1.0

    def test_empty_strings_return_0(self):
        """Test that empty strings return 0.0."""
        result = compare_string_date("", "")
        assert result == 0.0

    def test_empty_vs_valid_returns_0(self):
        """Test that empty string vs valid date returns 0.0."""
        assert compare_string_date("", "01/01/2024") == 0.0
        assert compare_string_date("01/01/2024", "") == 0.0

    # =========================================================================
    # Boundary Date Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted",
        [
            ("01/01/1900", "01011900"),
            ("31/12/2099", "31122099"),
            ("01/01/2000", "01012000"),  # Y2K boundary
            ("28/02/1900", "28021900"),  # 1900 was not a leap year
            ("1900-01-01", "19000101"),  # ISO year 1900
            ("2099-12-31", "20991231"),  # ISO year 2099
            ("2000-01-01", "01/01/2000"),  # ISO vs European Y2K
        ],
        ids=[
            "year_1900",
            "year_2099",
            "y2k_boundary",
            "1900_not_leap_year",
            "iso_year_1900",
            "iso_year_2099",
            "iso_vs_european_y2k",
        ],
    )
    def test_boundary_dates(self, expected: str, predicted: str):
        """Test dates at boundaries of typical date ranges."""
        result = compare_string_date(expected, predicted)
        assert result == 1.0

class TestMetricFunctionsMapping:
    """Test that STRING_DATE_EQUALITY is properly mapped in METRIC_FUNCTIONS."""

    def test_string_date_equality_in_metric_functions(self):
        """Test that STRING_DATE_EQUALITY maps to compare_string_date."""
        assert Metric.STRING_DATE_EQUALITY in METRIC_FUNCTIONS
        assert METRIC_FUNCTIONS[Metric.STRING_DATE_EQUALITY] == compare_string_date

    def test_metric_function_callable(self):
        """Test that the mapped function is callable and works correctly."""
        func = METRIC_FUNCTIONS[Metric.STRING_DATE_EQUALITY]
        assert callable(func)
        assert func("01/01/2024", "01012024") == 1.0
        assert func("01/01/2024", "02/01/2024") == 0.0


class TestRealWorldScenarios:
    """Test real-world scenarios commonly encountered in document processing."""

    @pytest.mark.parametrize(
        "expected,predicted,should_match",
        [
            # Tax documents (avis d'imposition) - common French date formats
            ("15/04/2024", "15042024", True),
            ("31/12/2023", "31/12/2023", True),
            # OCR sometimes adds spaces
            ("  15/04/2024  ", "15042024", True),
            # Different documents, same date
            ("01/01/2024", "01/01/2024", True),
            # Typos or OCR errors should fail
            ("15/04/2024", "15/04/2025", False),
            ("15/04/2024", "16/04/2024", False),
            # API responses often use ISO format
            ("2024-04-15", "15/04/2024", True),
            ("2024-12-31", "31122023", False),  # Wrong year
            # Database timestamps in ISO format
            ("2024-01-15", "20240115", True),
            ("2024/06/30", "30/06/2024", True),
            # Mixed system inputs
            ("01-01-2024", "2024-01-01", True),
            ("20240315", "15/03/2024", True),
        ],
        ids=[
            "tax_doc_cross_format",
            "tax_doc_same_format",
            "ocr_with_spaces",
            "same_date_same_format",
            "wrong_year",
            "wrong_day",
            "api_iso_vs_european",
            "iso_vs_european_wrong_year",
            "db_iso_vs_yyyymmdd",
            "iso_slash_vs_european",
            "european_dash_vs_iso",
            "yyyymmdd_vs_european",
        ],
    )
    def test_document_processing_scenarios(
        self, expected: str, predicted: str, should_match: bool
    ):
        """Test scenarios commonly encountered in document processing."""
        result = compare_string_date(expected, predicted)
        if should_match:
            assert result == 1.0
        else:
            assert result == 0.0

