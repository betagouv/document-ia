from datetime import date

import pytest
from pydantic import BaseModel

from document_ia_schemas.base_document_type_schema import (
    DateAnomalyCode,
    FuzzyDate,
    INVALID_DATE_CODE,
    InvalidProperty,
)


class _DateProbeModel(BaseModel):
    value: FuzzyDate = None


def test_invalid_property_attributes():
    instance = InvalidProperty(code=INVALID_DATE_CODE, raw_value="31/04/2026")
    assert instance.code == DateAnomalyCode.INVALID_DATE
    assert instance.raw_value == "31/04/2026"


@pytest.mark.parametrize(
    "raw_value",
    [
        "2026-02-29",
        "2024-02-30",
        "2024-02-31",
        "31/04/2026",
        "31-06-2026",
        "00/04/2026",
        "12/13/2026",
        "0000-01-01",
    ],
)
def test_fuzzy_date_preserves_invalid_date_as_anomaly(raw_value: str):
    model = _DateProbeModel(value=raw_value)
    assert model.value == InvalidProperty(
        code=INVALID_DATE_CODE, raw_value=raw_value
    )
    serialized = model.model_dump_json()
    assert _DateProbeModel.model_validate_json(serialized) == model
    assert model.model_dump(mode="json")["value"] == {
        "code": "invalid_date",
        "raw_value": raw_value,
    }


@pytest.mark.parametrize("raw_value", [None, "null", "None", "", "  "])
def test_missing_dates_remain_missing(raw_value):
    assert _DateProbeModel(value=raw_value).value is None


def test_anomaly_preserves_whitespace_during_deserialization():
    model = _DateProbeModel(
        value={
            "code": "invalid_date",
            "raw_value": " 31/04/2026 ",
        }
    )
    assert model.value == InvalidProperty(
        code=INVALID_DATE_CODE, raw_value=" 31/04/2026 "
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
