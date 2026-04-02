from datetime import date

from pydantic import BaseModel, BeforeValidator

from document_ia_infra.openai.response_format import get_response_format
from typing import Annotated, Optional


def _coerce_feb_29(value: str | None) -> date | None:
    if value == "2026-02-29":
        return date(2026, 2, 28)
    if value is None:
        return None
    return date.fromisoformat(value)


class _ProbeModel(BaseModel):
    period_end: Annotated[Optional[date], BeforeValidator(_coerce_feb_29)] = None


def test_get_response_format_preserves_and_executes_field_validators_on_model_validate():
    response_model = get_response_format(_ProbeModel)
    parsed = response_model.model_validate({"period_end": "2026-02-29"})

    assert parsed.period_end == date(2026, 2, 28)
