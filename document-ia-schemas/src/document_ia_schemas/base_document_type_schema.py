import re
from abc import ABC
from datetime import date
from typing import (
    TypeVar,
    Generic,
    Type,
    Any,
    Optional,
    Annotated,
    cast,
    Final,
    final,
)

from pydantic import BaseModel, ConfigDict, BeforeValidator

T = TypeVar("T", bound=BaseModel)

DATE_FORMAT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})$"),
    re.compile(r"^(?P<day>\d{1,2})-(?P<month>\d{1,2})-(?P<year>\d{4})$"),
    re.compile(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})$"),
]


@final
class DateAnomalyCode:
    """Anomaly codes for date values."""

    INVALID_DATE: Final[str] = "invalid_date"


INVALID_DATE_CODE: Final[str] = DateAnomalyCode.INVALID_DATE


class InvalidProperty(BaseModel):
    """An extracted candidate property that failed validation."""

    code: str
    raw_value: str


def _parse_date_candidate(raw_value: str) -> date | InvalidProperty | None:
    for pattern in DATE_FORMAT_PATTERNS:
        match = pattern.fullmatch(raw_value)
        if match is None:
            continue

        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))

        try:
            return date(year, month, day)
        except ValueError:
            return InvalidProperty(code=INVALID_DATE_CODE, raw_value=raw_value)

    return None


def parse_flexible_date(value: Any) -> date | InvalidProperty | None:
    """
    Tente de convertir une chaîne en date en essayant plusieurs formats.
    Gère aussi les cas où le LLM renvoie 'null' ou 'None' en string.
    """
    if value is None:
        return None

    # Si c'est déjà une date (ex: conversion automatique de certaines lib)
    if isinstance(value, date):
        return value

    # Recompute anomalies on deserialization rather than trusting a supplied anomaly.
    if isinstance(value, InvalidProperty):
        value = value.raw_value
    elif isinstance(value, dict):
        anomaly_data = cast(dict[str, Any], value)
        if (
            anomaly_data.get("code") == INVALID_DATE_CODE
            and "raw_value" in anomaly_data
        ):
            value = anomaly_data.get("raw_value")

    if isinstance(value, str):
        raw_value = value
        value = value.strip()
        # Gestion des cas où le LLM écrit littéralement "null" ou "None"
        if value.lower() in ["null", "none", ""]:
            return None

        parsed_date = _parse_date_candidate(value)
        if parsed_date is not None:
            if isinstance(parsed_date, InvalidProperty):
                parsed_date.raw_value = raw_value
            return parsed_date

    # Si rien n'a marché, on laisse Pydantic lever l'erreur ou on renvoie None selon ta politique
    # Ici, je lève une erreur pour que tu saches que l'extraction a échoué sur ce champ
    raise ValueError(f"Format de date non reconnu : {value}")


def _validate_fuzzy_date(value: Any) -> date | dict[str, Any] | None:
    parsed = parse_flexible_date(value)
    # The OpenAI adapter rebuilds nested models; a dict works for both model classes.
    return parsed.model_dump() if isinstance(parsed, InvalidProperty) else parsed


FuzzyDate = Annotated[
    Optional[date | InvalidProperty], BeforeValidator(_validate_fuzzy_date)
]


class BaseDocumentTypeSchema(BaseModel, Generic[T], ABC):  # pyright: ignore [reportUnsafeMultipleInheritance]
    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str = ""
    name: str = ""
    description: list[str] = []
    examples: list[T] = []
    document_model: Type[T]

    # Clés à exclure du JSON Schema (issues de json_schema_extra sur les champs)
    # Ajustable par sous-classe si besoin (ex: {"metrics", "x-internal"})
    schema_extra_keys_excluded: set[str] = {"metrics"}

    def get_document_description_dict(self) -> dict[str, Any]:
        return {"type": self.type, "name": self.name, "description": self.description}

    def _strip_keys_recursive(self, obj: Any, keys_to_strip: set[str]) -> Any:
        """Supprime récursivement les clés spécifiées dans n'importe quel dict du schéma.

        - Parcourt dicts et lists
        - Retire les clés présentes dans keys_to_strip
        - Retourne l'objet (muté) pour chaînage
        """
        if isinstance(obj, dict):
            for k in list(obj.keys()):  # pyright: ignore [reportUnknownArgumentType, reportUnknownVariableType]
                if k in keys_to_strip:
                    obj.pop(k, None)  # pyright: ignore [reportUnknownMemberType, reportUnknownArgumentType]
                else:
                    obj[k] = self._strip_keys_recursive(obj[k], keys_to_strip)
        elif isinstance(obj, list):
            for i in range(len(obj)):  # pyright: ignore [reportUnknownArgumentType]
                obj[i] = self._strip_keys_recursive(obj[i], keys_to_strip)
        return obj  # pyright: ignore [reportUnknownVariableType]

    def get_json_schema_dict(self) -> dict[str, Any]:
        schema = self.document_model.model_json_schema(by_alias=False)
        # Nettoie les clés supplémentaires (json_schema_extra) si configurées
        if self.schema_extra_keys_excluded:
            schema = self._strip_keys_recursive(schema, self.schema_extra_keys_excluded)
        return schema
