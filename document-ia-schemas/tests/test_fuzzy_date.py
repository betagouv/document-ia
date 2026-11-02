from datetime import date

import pytest
from pydantic import BaseModel

from document_ia_schemas.base_document_type_schema import FuzzyDate, InvalidDate


class _DateProbeModel(BaseModel):
    value: FuzzyDate = None


@pytest.mark.parametrize(
    ("raw_value", "expected_value"),
    [
        ("2026-02-29", date(2026, 2, 28)),
        ("2024-02-30", date(2024, 2, 29)),
        ("2024-02-31", date(2024, 2, 29)),
        ("31/04/2026", date(2026, 4, 30)),
        ("31-06-2026", date(2026, 6, 30)),
    ],
)
def test_fuzzy_date_preserves_invalid_day_and_separates_suggestion(
    raw_value: str, expected_value: date
):
    model = _DateProbeModel(value=raw_value)
    assert model.value == InvalidDate(
        raw_value=raw_value, suggested_value=expected_value
    )
    serialized = model.model_dump_json()
    assert _DateProbeModel.model_validate_json(serialized) == model
    assert model.model_dump(mode="json")["value"] == {
        "code": "invalid_date",
        "raw_value": raw_value,
        "suggested_value": expected_value.isoformat(),
    }


@pytest.mark.parametrize("raw_value", ["00/04/2026", "12/13/2026", "0000-01-01"])
def test_impossible_dates_without_a_safe_suggestion(raw_value):
    model = _DateProbeModel(value=raw_value)
    assert model.value == InvalidDate(raw_value=raw_value)
    assert _DateProbeModel.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("raw_value", [None, "null", "None", "", "  "])
def test_missing_dates_remain_missing(raw_value):
    assert _DateProbeModel(value=raw_value).value is None


def test_anomaly_preserves_whitespace_and_recomputes_untrusted_suggestion():
    model = _DateProbeModel(
        value={
            "code": "invalid_date",
            "raw_value": " 31/04/2026 ",
            "suggested_value": "2000-01-01",
        }
    )
    assert model.value == InvalidDate(
        raw_value=" 31/04/2026 ", suggested_value=date(2026, 4, 30)
    )


def test_fuzzy_date_keeps_valid_date_unchanged():
    model = _DateProbeModel(value="2026-05-31")
    assert model.value == date(2026, 5, 31)


@pytest.mark.parametrize(
    ("raw_value", "expected_value"),
    [
        ("2024-1-1", date(2024, 1, 1)),
        ("1/1/2024", date(2024, 1, 1)),
        ("9/12/2023", date(2023, 12, 9)),
        ("1-1-2024", date(2024, 1, 1)),
        ("1.1.2024", date(2024, 1, 1)),
    ],
)
def test_fuzzy_date_accepts_single_digit_day_and_month(
    raw_value: str, expected_value: date
):
    model = _DateProbeModel(value=raw_value)
    assert model.value == expected_value


def test_fuzzy_date_rejects_unparseable_value():
    with pytest.raises(ValueError, match="Format de date non reconnu"):
        _DateProbeModel(value="not-a-date")
