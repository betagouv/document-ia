import calendar
import logging
import re
from abc import ABC
from datetime import date
from typing import TypeVar, Generic, Type, Any, Optional, Annotated

from pydantic import BaseModel, ConfigDict, BeforeValidator

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)

DATE_FORMAT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})$"),
    re.compile(r"^(?P<day>\d{1,2})-(?P<month>\d{1,2})-(?P<year>\d{4})$"),
    re.compile(r"^(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})$"),
]


def _parse_date_with_day_clamp(raw_value: str) -> Optional[date]:
    for pattern in DATE_FORMAT_PATTERNS:
        match = pattern.fullmatch(raw_value)
        if match is None:
            continue

        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))

        if month < 1 or month > 12 or day < 1:
            raise ValueError(f"Format de date non reconnu : {raw_value}")

        max_day = calendar.monthrange(year, month)[1]
        normalized_day = min(day, max_day)
        normalized_date = date(year, month, normalized_day)

        if normalized_day != day:
            logger.warning(
                "Corrected invalid date value during extraction normalization: input=%s corrected=%s",
                raw_value,
                normalized_date.isoformat(),
            )

        return normalized_date

    return None


def parse_flexible_date(value: Any) -> Optional[date]:
    """
    Tente de convertir une chaîne en date en essayant plusieurs formats.
    Gère aussi les cas où le LLM renvoie 'null' ou 'None' en string.
    """
    if value is None:
        return None

    # Si c'est déjà une date (ex: conversion automatique de certaines lib)
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()
        # Gestion des cas où le LLM écrit littéralement "null" ou "None"
        if value.lower() in ["null", "none", ""]:
            return None

        parsed_date = _parse_date_with_day_clamp(value)
        if parsed_date is not None:
            return parsed_date

    # Si rien n'a marché, on laisse Pydantic lever l'erreur ou on renvoie None selon ta politique
    # Ici, je lève une erreur pour que tu saches que l'extraction a échoué sur ce champ
    raise ValueError(f"Format de date non reconnu : {value}")

FuzzyDate = Annotated[Optional[date], BeforeValidator(parse_flexible_date)]


class BaseDocumentTypeSchema(BaseModel, Generic[T], ABC):
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
