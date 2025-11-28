"""
Comprehensive unit tests for LEVENSHTEIN_DISTANCE metric.

This module tests the levenshtein_distance, levenshtein_similarity, 
and compare_levenshtein functions that implement string comparison
using the Levenshtein (edit) distance algorithm.

Note: The Levenshtein functions are case-insensitive and ignore:
- Whitespace
- Punctuation (., -, _, ')
- French accents (é→e, è→e, ê→e, à→a, ù→u, ç→c, etc.)
"""

import pytest

from document_ia_evals.metrics.compare_functions import (
    compare_levenshtein,
    levenshtein_distance,
    levenshtein_similarity,
    normalize_for_levenshtein,
    METRIC_FUNCTIONS,
)
from document_ia_schemas.field_metrics import Metric


class TestNormalizeForLevenshtein:
    """Test cases for the normalize_for_levenshtein function."""

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            # Case normalization
            ("ABC", "abc"),
            ("Hello", "hello"),
            ("HELLO WORLD", "helloworld"),
            # Whitespace removal
            ("hello world", "helloworld"),
            ("hello  world", "helloworld"),
            ("  hello  ", "hello"),
            ("hello\tworld", "helloworld"),
            ("hello\nworld", "helloworld"),
            # Punctuation removal
            ("Jean-Pierre", "jeanpierre"),
            ("O'Connor", "oconnor"),
            ("file.txt", "filetxt"),
            ("hello_world", "helloworld"),
            # Combined
            ("Jean-Pierre O'Connor", "jeanpierreoconnor"),
            ("Hello.World", "helloworld"),
            ("HELLO_WORLD", "helloworld"),
        ],
        ids=[
            "uppercase",
            "mixed_case",
            "uppercase_with_space",
            "single_space",
            "double_space",
            "leading_trailing_space",
            "tab",
            "newline",
            "hyphen",
            "apostrophe",
            "dot",
            "underscore",
            "combined_punctuation",
            "dot_separator",
            "underscore_uppercase",
        ],
    )
    def test_normalization(self, input_str: str, expected: str):
        """Test that strings are properly normalized."""
        result = normalize_for_levenshtein(input_str)
        assert result == expected

    @pytest.mark.parametrize(
        "input_str,expected",
        [
            # é variants
            ("Rémy", "remy"),
            ("café", "cafe"),
            ("éléphant", "elephant"),
            # è variants
            ("père", "pere"),
            ("mère", "mere"),
            # ê variants
            ("être", "etre"),
            ("fête", "fete"),
            ("Île", "ile"),
            # ë variants
            ("Noël", "noel"),
            # à variants
            ("à", "a"),
            ("voilà", "voila"),
            # â variants
            ("château", "chateau"),
            ("pâte", "pate"),
            # ù variants
            ("où", "ou"),
            # û variants
            ("dû", "du"),
            ("sûr", "sur"),
            # î variants
            ("Maître", "maitre"),
            ("île", "ile"),
            # ï variants
            ("naïf", "naif"),
            ("Loïc", "loic"),
            # ô variants
            ("hôtel", "hotel"),
            ("côte", "cote"),
            # ç variants
            ("ça", "ca"),
            ("français", "francais"),
            ("reçu", "recu"),
            ("garçon", "garcon"),
            # ÿ variants
            ("Aÿ", "ay"),
            # œ ligature
            ("cœur", "coeur"),
            ("sœur", "soeur"),
            # æ ligature
            ("curriculum vitæ", "curriculumvitae"),
            # Combined examples
            ("François", "francois"),
            ("Hélène", "helene"),
            ("Jérôme", "jerome"),
            ("Benoît", "benoit"),
        ],
        ids=[
            "e_acute_remy",
            "e_acute_cafe",
            "e_acute_elephant",
            "e_grave_pere",
            "e_grave_mere",
            "e_circumflex_etre",
            "e_circumflex_fete",
            "e_circumflex_ile",
            "e_diaeresis_noel",
            "a_grave_single",
            "a_grave_voila",
            "a_circumflex_chateau",
            "a_circumflex_pate",
            "u_grave_ou",
            "u_circumflex_du",
            "u_circumflex_sur",
            "i_circumflex_maitre",
            "i_circumflex_ile",
            "i_diaeresis_naif",
            "i_diaeresis_loic",
            "o_circumflex_hotel",
            "o_circumflex_cote",
            "c_cedilla_ca",
            "c_cedilla_francais",
            "c_cedilla_recu",
            "c_cedilla_garcon",
            "y_diaeresis_ay",
            "oe_ligature_coeur",
            "oe_ligature_soeur",
            "ae_ligature",
            "combined_francois",
            "combined_helene",
            "combined_jerome",
            "combined_benoit",
        ],
    )
    def test_french_accent_normalization(self, input_str: str, expected: str):
        """Test that French accents are properly normalized."""
        result = normalize_for_levenshtein(input_str)
        assert result == expected


class TestLevenshteinDistance:
    """Test cases for the levenshtein_distance function."""

    # =========================================================================
    # Identical Strings Tests (after normalization)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("", "", 0),
            ("a", "a", 0),
            ("abc", "abc", 0),
            ("hello", "hello", 0),
            ("12345", "12345", 0),
            ("café", "café", 0),
        ],
        ids=[
            "empty_strings",
            "single_char",
            "three_chars",
            "word",
            "digits",
            "unicode",
        ],
    )
    def test_identical_strings(self, s1: str, s2: str, expected: int):
        """Test that identical strings have distance 0."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Case Insensitivity Tests (distance = 0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("abc", "ABC", 0),
            ("Hello", "hello", 0),
            ("HELLO", "hello", 0),
            ("HeLLo", "hello", 0),
            ("DUPONT", "dupont", 0),
            ("Jean", "JEAN", 0),
        ],
        ids=[
            "lower_vs_upper",
            "first_char_case",
            "all_caps_vs_lower",
            "mixed_case",
            "name_case",
            "first_name_case",
        ],
    )
    def test_case_insensitivity(self, s1: str, s2: str, expected: int):
        """Test that case differences are ignored."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Whitespace Insensitivity Tests (distance = 0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("hello world", "helloworld", 0),
            ("hello  world", "hello world", 0),
            ("hello", " hello", 0),
            ("hello ", "hello", 0),
            ("  hello  ", "hello", 0),
            ("hello\tworld", "hello world", 0),
            ("hello\nworld", "helloworld", 0),
            ("Jean Pierre", "JeanPierre", 0),
        ],
        ids=[
            "single_space_removed",
            "double_vs_single_space",
            "leading_space",
            "trailing_space",
            "leading_trailing_spaces",
            "tab_vs_space",
            "newline_removed",
            "name_with_space",
        ],
    )
    def test_whitespace_insensitivity(self, s1: str, s2: str, expected: int):
        """Test that whitespace differences are ignored."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Punctuation Insensitivity Tests (distance = 0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("Jean-Pierre", "JeanPierre", 0),
            ("Jean-Pierre", "Jean Pierre", 0),
            ("O'Connor", "OConnor", 0),
            ("O'Connor", "O Connor", 0),
            ("hello.world", "helloworld", 0),
            ("hello_world", "helloworld", 0),
            ("hello-world", "hello_world", 0),
            ("file.name.txt", "filenametxt", 0),
            ("it's", "its", 0),
            ("don't", "dont", 0),
        ],
        ids=[
            "hyphen_removed",
            "hyphen_vs_space",
            "apostrophe_removed",
            "apostrophe_vs_space",
            "dot_removed",
            "underscore_removed",
            "hyphen_vs_underscore",
            "multiple_dots",
            "contraction_its",
            "contraction_dont",
        ],
    )
    def test_punctuation_insensitivity(self, s1: str, s2: str, expected: int):
        """Test that punctuation differences are ignored."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # French Accent Insensitivity Tests (distance = 0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            # é → e
            ("Rémy", "Remy", 0),
            ("café", "cafe", 0),
            ("éléphant", "elephant", 0),
            # è → e
            ("père", "pere", 0),
            ("mère", "mere", 0),
            # ê → e
            ("être", "etre", 0),
            ("fête", "fete", 0),
            ("Île", "Ile", 0),
            # ë → e
            ("Noël", "Noel", 0),
            # à → a
            ("À", "A", 0),
            ("voilà", "voila", 0),
            # â → a
            ("château", "chateau", 0),
            # ù → u
            ("où", "ou", 0),
            # û → u
            ("sûr", "sur", 0),
            # î → i
            ("Maître", "Maitre", 0),
            ("île", "ile", 0),
            # ï → i
            ("naïf", "naif", 0),
            # ô → o
            ("hôtel", "hotel", 0),
            # ç → c
            ("ça", "ca", 0),
            ("français", "francais", 0),
            ("garçon", "garcon", 0),
            # œ → oe
            ("cœur", "coeur", 0),
            ("sœur", "soeur", 0),
            # Combined with case
            ("FRANÇOIS", "francois", 0),
            ("HÉLÈNE", "Helene", 0),
            ("Jérôme", "JEROME", 0),
        ],
        ids=[
            "e_acute_remy",
            "e_acute_cafe",
            "e_acute_elephant",
            "e_grave_pere",
            "e_grave_mere",
            "e_circumflex_etre",
            "e_circumflex_fete",
            "e_circumflex_ile_upper",
            "e_diaeresis_noel",
            "a_grave_upper",
            "a_grave_voila",
            "a_circumflex_chateau",
            "u_grave_ou",
            "u_circumflex_sur",
            "i_circumflex_maitre",
            "i_circumflex_ile",
            "i_diaeresis_naif",
            "o_circumflex_hotel",
            "c_cedilla_ca",
            "c_cedilla_francais",
            "c_cedilla_garcon",
            "oe_ligature_coeur",
            "oe_ligature_soeur",
            "combined_francois",
            "combined_helene",
            "combined_jerome",
        ],
    )
    def test_french_accent_insensitivity(self, s1: str, s2: str, expected: int):
        """Test that French accent differences are ignored."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Single Edit Tests (distance = 1)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            # Insertion
            ("abc", "abcd", 1),
            ("abc", "xabc", 1),
            ("abc", "axbc", 1),
            # Deletion
            ("abcd", "abc", 1),
            ("xabc", "abc", 1),
            ("axbc", "abc", 1),
            # Substitution
            ("abc", "xbc", 1),
            ("abc", "axc", 1),
            ("abc", "abx", 1),
        ],
        ids=[
            "insert_end",
            "insert_start",
            "insert_middle",
            "delete_end",
            "delete_start",
            "delete_middle",
            "substitute_start",
            "substitute_middle",
            "substitute_end",
        ],
    )
    def test_single_edit(self, s1: str, s2: str, expected: int):
        """Test strings that differ by exactly one edit."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Multiple Edits Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("abc", "xyz", 3),  # 3 substitutions
            ("abc", "abcdef", 3),  # 3 insertions
            ("abcdef", "abc", 3),  # 3 deletions
            ("kitten", "sitting", 3),  # Classic example: k->s, e->i, +g
            ("saturday", "sunday", 3),  # Classic example
            ("flaw", "lawn", 2),  # f->l, +n or substitute
        ],
        ids=[
            "all_substitutions",
            "all_insertions",
            "all_deletions",
            "kitten_sitting",
            "saturday_sunday",
            "flaw_lawn",
        ],
    )
    def test_multiple_edits(self, s1: str, s2: str, expected: int):
        """Test strings requiring multiple edits."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Empty String Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("", "a", 1),
            ("", "abc", 3),
            ("", "hello", 5),
            ("a", "", 1),
            ("abc", "", 3),
            ("hello", "", 5),
            # Whitespace-only strings become empty
            ("", "   ", 0),
            ("   ", "", 0),
            ("", "---", 0),  # Punctuation-only becomes empty
        ],
        ids=[
            "empty_to_single",
            "empty_to_three",
            "empty_to_word",
            "single_to_empty",
            "three_to_empty",
            "word_to_empty",
            "empty_vs_spaces",
            "spaces_vs_empty",
            "empty_vs_punctuation",
        ],
    )
    def test_empty_string(self, s1: str, s2: str, expected: int):
        """Test distance from/to empty strings."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Symmetry Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2",
        [
            ("abc", "def"),
            ("hello", "world"),
            ("kitten", "sitting"),
            ("", "abc"),
            ("Jean-Pierre", "JeanPierre"),
        ],
        ids=[
            "abc_def",
            "hello_world",
            "kitten_sitting",
            "empty_abc",
            "hyphen_vs_none",
        ],
    )
    def test_symmetry(self, s1: str, s2: str):
        """Test that distance(s1, s2) == distance(s2, s1)."""
        assert levenshtein_distance(s1, s2) == levenshtein_distance(s2, s1)

    # =========================================================================
    # Unicode and Special Characters Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            # French accents are normalized (distance = 0)
            ("café", "cafe", 0),
            ("naïve", "naive", 0),
            ("résumé", "resume", 0),
            # German umlaut ü is same as French ü, so also normalized
            ("über", "uber", 0),
            # Other unicode - NOT normalized
            ("日本", "日本語", 1),
            ("🎉", "🎊", 1),
        ],
        ids=[
            "french_accent_e",
            "french_diaeresis_i",
            "french_two_accents",
            "german_umlaut_u",
            "japanese_kanji",
            "emoji",
        ],
    )
    def test_unicode(self, s1: str, s2: str, expected: int):
        """Test handling of unicode characters (French accents ARE normalized)."""
        result = levenshtein_distance(s1, s2)
        assert result == expected

    # =========================================================================
    # Real-World Document OCR Errors Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            ("DUPONT", "DUP0NT", 1),  # O vs 0 (case insensitive)
            ("12345", "I2345", 1),  # 1 vs I
            ("hello", "hel1o", 1),  # l vs 1
            ("SMITH", "SMIITH", 1),  # double letter
            ("address", "adress", 1),  # missing letter
        ],
        ids=[
            "o_vs_zero",
            "one_vs_i",
            "l_vs_one",
            "double_letter",
            "missing_letter",
        ],
    )
    def test_ocr_errors(self, s1: str, s2: str, expected: int):
        """Test typical OCR error patterns."""
        result = levenshtein_distance(s1, s2)
        assert result == expected


class TestLevenshteinSimilarity:
    """Test cases for the levenshtein_similarity function."""

    # =========================================================================
    # Perfect Match Tests (similarity = 1.0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2",
        [
            ("", ""),
            ("a", "a"),
            ("abc", "abc"),
            ("hello", "hello"),
            ("12345", "12345"),
            # Case insensitive matches
            ("Hello", "hello"),
            ("ABC", "abc"),
            # Whitespace insensitive matches
            ("hello world", "helloworld"),
            ("Jean Pierre", "JeanPierre"),
            # Punctuation insensitive matches
            ("Jean-Pierre", "JeanPierre"),
            ("O'Connor", "OConnor"),
            # French accent insensitive matches
            ("café", "cafe"),
            ("François", "francois"),
            ("Hélène", "helene"),
            ("Rémy", "remy"),
            ("Noël", "noel"),
        ],
        ids=[
            "empty_strings",
            "single_char",
            "three_chars",
            "word",
            "digits",
            "case_diff",
            "case_diff_all",
            "space_diff",
            "name_space",
            "hyphen_diff",
            "apostrophe_diff",
            "french_cafe",
            "french_francois",
            "french_helene",
            "french_remy",
            "french_noel",
        ],
    )
    def test_perfect_match(self, s1: str, s2: str):
        """Test that normalized identical strings have similarity 1.0."""
        result = levenshtein_similarity(s1, s2)
        assert result == 1.0

    # =========================================================================
    # Complete Mismatch Tests (similarity = 0.0)
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2",
        [
            ("", "abc"),
            ("abc", ""),
            ("", "x"),
            ("x", ""),
            ("abc", "xyz"),  # All different
        ],
        ids=[
            "empty_vs_abc",
            "abc_vs_empty",
            "empty_vs_single",
            "single_vs_empty",
            "all_different",
        ],
    )
    def test_zero_similarity(self, s1: str, s2: str):
        """Test cases with zero similarity."""
        result = levenshtein_similarity(s1, s2)
        assert result == 0.0

    # =========================================================================
    # Partial Match Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2,expected_min,expected_max",
        [
            ("abc", "abd", 0.6, 0.7),  # 2/3 match
            ("hello", "hallo", 0.7, 0.9),  # 4/5 match
            ("kitten", "sitting", 0.5, 0.6),  # 4/7 match approx
        ],
        ids=[
            "one_char_diff",
            "one_vowel_diff",
            "kitten_sitting",
        ],
    )
    def test_partial_match_range(
        self, s1: str, s2: str, expected_min: float, expected_max: float
    ):
        """Test that partial matches fall within expected similarity ranges."""
        result = levenshtein_similarity(s1, s2)
        assert expected_min <= result <= expected_max

    # =========================================================================
    # Symmetry Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "s1,s2",
        [
            ("abc", "def"),
            ("hello", "world"),
            ("kitten", "sitting"),
            ("ab", "abc"),
        ],
        ids=[
            "abc_def",
            "hello_world",
            "kitten_sitting",
            "ab_abc",
        ],
    )
    def test_symmetry(self, s1: str, s2: str):
        """Test that similarity(s1, s2) == similarity(s2, s1)."""
        assert levenshtein_similarity(s1, s2) == levenshtein_similarity(s2, s1)


class TestCompareLevenshtein:
    """Test cases for the compare_levenshtein function."""

    # =========================================================================
    # String Comparison Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted,similarity",
        [
            ("hello", "hello", 1.0),
            ("Hello", "hello", 1.0),  # Case insensitive
            ("Jean-Pierre", "Jean Pierre", 1.0),  # Punctuation insensitive
            ("abc", "xyz", 0.0),  # All different
        ],
        ids=[
            "identical",
            "case_diff",
            "hyphen_vs_space",
            "all_different",
        ],
    )
    def test_string_comparison(
        self, expected: str, predicted: str, similarity: float
    ):
        """Test string comparison using Levenshtein."""
        result = compare_levenshtein(expected, predicted)
        assert result == similarity

    # =========================================================================
    # None Handling Tests
    # =========================================================================

    def test_both_none(self):
        """Test that both None values are treated as empty strings (similarity 1.0)."""
        result = compare_levenshtein(None, None)
        assert result == 1.0

    def test_expected_none(self):
        """Test that None expected is treated as empty string."""
        result = compare_levenshtein(None, "hello")
        assert result == 0.0

    def test_predicted_none(self):
        """Test that None predicted is treated as empty string."""
        result = compare_levenshtein("hello", None)
        assert result == 0.0

    # =========================================================================
    # Real-World Name Comparison Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted,similarity",
        [
            # Case and punctuation insensitive - perfect matches
            ("DUPONT", "dupont", 1.0),
            ("Jean-Pierre", "JEAN PIERRE", 1.0),
            ("O'Connor", "OCONNOR", 1.0),
            ("Marie-Claire", "MARIE CLAIRE", 1.0),
            # French names with accents (accents ARE now normalized)
            ("François", "Francois", 1.0),
            ("Hélène", "Helene", 1.0),
            ("Rémy", "Remy", 1.0),
            ("Benoît", "Benoit", 1.0),
            # Common typos
            ("Martin", "Matin", 0.833),  # 1/6 ≈ 0.83
        ],
        ids=[
            "name_case",
            "hyphen_vs_space",
            "apostrophe_name",
            "compound_name",
            "francois_accent",
            "helene_accent",
            "remy_accent",
            "benoit_accent",
            "martin_typo",
        ],
    )
    def test_name_comparison(
        self, expected: str, predicted: str, similarity: float
    ):
        """Test name comparison with typical variations."""
        result = compare_levenshtein(expected, predicted)
        assert abs(result - similarity) < 0.01

    # =========================================================================
    # Address Comparison Tests
    # =========================================================================

    @pytest.mark.parametrize(
        "expected,predicted,similarity",
        [
            ("123 rue de Paris", "123 RUE DE PARIS", 1.0),  # Case insensitive
            ("123 rue de Paris", "123ruedeparis", 1.0),  # Space insensitive
            ("15 RUE DE LA PAIX", "15 RUE DE LA PAX", 0.923),  # 1/13 diff
        ],
        ids=[
            "address_case",
            "address_no_spaces",
            "address_typo",
        ],
    )
    def test_address_comparison(
        self, expected: str, predicted: str, similarity: float
    ):
        """Test address comparison scenarios."""
        result = compare_levenshtein(expected, predicted)
        assert abs(result - similarity) < 0.01


class TestMetricFunctionsMapping:
    """Test that LEVENSHTEIN_DISTANCE is properly mapped in METRIC_FUNCTIONS."""

    def test_levenshtein_in_metric_functions(self):
        """Test that LEVENSHTEIN_DISTANCE maps to compare_levenshtein."""
        assert Metric.LEVENSHTEIN_DISTANCE in METRIC_FUNCTIONS
        assert METRIC_FUNCTIONS[Metric.LEVENSHTEIN_DISTANCE] == compare_levenshtein

    def test_metric_function_callable(self):
        """Test that the mapped function is callable and works correctly."""
        func = METRIC_FUNCTIONS[Metric.LEVENSHTEIN_DISTANCE]
        assert callable(func)
        assert func("hello", "hello") == 1.0
        assert func("HELLO", "hello") == 1.0  # Case insensitive
        assert func("abc", "xyz") == 0.0


class TestRealWorldScenarios:
    """Test real-world scenarios commonly encountered in document processing."""

    @pytest.mark.parametrize(
        "expected,predicted,similarity",
        [
            # Identity documents - names (case/space/punctuation insensitive)
            ("DUPONT", "dupont", 1.0),
            ("JEAN-PIERRE", "Jean Pierre", 1.0),
            ("O'CONNOR", "O Connor", 1.0),
            # OCR errors (still detected)
            ("DUPONT", "DUP0NT", 0.833),  # O vs 0, 1/6
            ("MARIE", "MARI", 0.8),  # Missing E, 1/5
            # Addresses
            ("15 RUE DE LA PAIX", "15rueDelapAix", 1.0),
        ],
        ids=[
            "exact_name_case",
            "hyphen_vs_space_case",
            "apostrophe_vs_space",
            "ocr_o_zero",
            "missing_letter",
            "address_normalized",
        ],
    )
    def test_identity_document_scenarios(
        self, expected: str, predicted: str, similarity: float
    ):
        """Test scenarios from identity document processing."""
        result = compare_levenshtein(expected, predicted)
        assert abs(result - similarity) < 0.01

    @pytest.mark.parametrize(
        "expected,predicted,similarity",
        [
            # Tax document - taxpayer names
            ("MARTIN DUPONT", "martin.dupont", 1.0),
            ("MARTIN_DUPONT", "Martin Dupont", 1.0),
            # Reference numbers
            ("2024ABC123", "2024abc123", 1.0),
            ("2024-ABC-123", "2024ABC123", 1.0),
        ],
        ids=[
            "taxpayer_space_vs_dot",
            "taxpayer_underscore_vs_space",
            "reference_case",
            "reference_hyphen",
        ],
    )
    def test_tax_document_scenarios(
        self, expected: str, predicted: str, similarity: float
    ):
        """Test scenarios from tax document processing."""
        result = compare_levenshtein(expected, predicted)
        assert abs(result - similarity) < 0.01


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_strings(self):
        """Test with very long strings."""
        s1 = "a" * 1000
        s2 = "a" * 1000
        assert levenshtein_distance(s1, s2) == 0
        assert levenshtein_similarity(s1, s2) == 1.0

    def test_long_strings_one_diff(self):
        """Test long strings with one difference."""
        s1 = "a" * 100
        s2 = "a" * 99 + "b"
        assert levenshtein_distance(s1, s2) == 1
        assert levenshtein_similarity(s1, s2) == 0.99

    def test_completely_different_same_length(self):
        """Test completely different strings of same length."""
        s1 = "aaaa"
        s2 = "bbbb"
        assert levenshtein_distance(s1, s2) == 4
        assert levenshtein_similarity(s1, s2) == 0.0

    def test_only_punctuation_differences(self):
        """Test strings that only differ in punctuation."""
        assert levenshtein_distance("hello-world", "hello_world") == 0
        assert levenshtein_distance("it's", "its") == 0
        assert levenshtein_similarity("Jean-Pierre", "Jean.Pierre") == 1.0

    def test_only_case_differences(self):
        """Test strings that only differ in case."""
        assert levenshtein_distance("HELLO", "hello") == 0
        assert levenshtein_distance("HeLLo WoRLd", "hello world") == 0
        assert levenshtein_similarity("ABC", "abc") == 1.0

    def test_only_whitespace_differences(self):
        """Test strings that only differ in whitespace."""
        assert levenshtein_distance("hello world", "helloworld") == 0
        assert levenshtein_distance("a b c", "abc") == 0
        assert levenshtein_similarity("Jean Pierre", "JeanPierre") == 1.0

    def test_combined_normalization(self):
        """Test combined case, whitespace, and punctuation normalization."""
        assert levenshtein_distance("JEAN-PIERRE O'CONNOR", "jean pierre oconnor") == 0
        assert levenshtein_similarity("Hello.World_Test-Case", "helloworldtestcase") == 1.0

    def test_only_french_accent_differences(self):
        """Test strings that only differ in French accents."""
        assert levenshtein_distance("café", "cafe") == 0
        assert levenshtein_distance("Rémy", "Remy") == 0
        assert levenshtein_distance("Noël", "Noel") == 0
        assert levenshtein_distance("Île", "Ile") == 0
        assert levenshtein_distance("Maître", "Maitre") == 0
        assert levenshtein_distance("français", "francais") == 0
        assert levenshtein_similarity("François", "Francois") == 1.0
        assert levenshtein_similarity("Hélène", "Helene") == 1.0

    def test_combined_french_accent_normalization(self):
        """Test combined case, whitespace, punctuation, and French accent normalization."""
        assert levenshtein_distance("FRANÇOIS HÉLÈNE", "francois helene") == 0
        assert levenshtein_distance("Jean-François O'Rémy", "jeanfrancoisoremy") == 0
        assert levenshtein_similarity("Ça va très bien", "cavatresbien") == 1.0

    def test_oe_ligature(self):
        """Test œ ligature normalization."""
        assert levenshtein_distance("cœur", "coeur") == 0
        assert levenshtein_distance("sœur", "soeur") == 0
        assert levenshtein_similarity("œuf", "oeuf") == 1.0
