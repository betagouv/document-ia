from logging.config import dictConfig
from typing import Any

from document_ia_infra.core.loki_settings import (
    build_loki_handler,
    LokiTagsFilter,
    logging_settings,
)


def build_loki_handler_for_app():
    return build_loki_handler(app_name="document-ia-worker")


def _get_filters() -> dict[str, Any]:
    if logging_settings.LOKI_LOGGING_ENABLED:
        return {
            "add_loki_tags": {"()": LokiTagsFilter},
        }
    else:
        return {}


def _get_handlers() -> dict[str, Any]:
    handlers_dict: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "std",
            "level": "INFO",
        },
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        handlers_dict["loki"] = {
            "()": "document_ia_worker.config.logging.build_loki_handler_for_app",
            "level": "INFO",
            "formatter": "std",
            "filters": ["add_loki_tags"],
        }
        handlers_dict["loki_json"] = {
            "()": "document_ia_worker.config.logging.build_loki_handler_for_app",
            "level": "INFO",
            "formatter": "message_only",
            "filters": ["add_loki_tags"],
        }

    return handlers_dict


def _get_loggers() -> dict[str, Any]:
    loggers_dict: dict[str, Any] = {
        "aggregator": {
            "handlers": [],
            "level": "INFO",
            "propagate": False,
        }
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        loggers_dict["aggregator"]["handlers"].append("loki_json")

    return loggers_dict


def _get_root_logger() -> dict[str, Any]:
    root_logger_dict: dict[str, Any] = {
        "handlers": ["console"],
        "level": "INFO",
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        root_logger_dict["handlers"].append("loki")

    return root_logger_dict


def setup_logging():
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": _get_filters(),
            "formatters": {
                "std": {
                    "format": "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s",
                },
                "message_only": {"format": "%(message)s"},
            },
            "handlers": _get_handlers(),
            "loggers": _get_loggers(),
            "root": _get_root_logger(),
        }
    )
