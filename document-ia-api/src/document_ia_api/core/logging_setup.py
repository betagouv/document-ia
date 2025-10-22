from contextvars import ContextVar
from datetime import datetime, timezone
from logging import Filter, LogRecord, Handler
from logging.config import dictConfig
from typing import Optional, Any, Dict, List

from document_ia_infra.core.loki_settings import (
    LokiTagsFilter,
    build_loki_handler,
    logging_settings,
)

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
agg_buffer_var: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "agg_buffer", default=None
)


def build_loki_handler_for_app():
    return build_loki_handler(app_name="document-ia-api")


class ContextRequestIdFilter(Filter):
    """Injecte request_id in every LogRecord if present inside contextvar."""

    def filter(self, record: LogRecord) -> bool:
        rid = request_id_var.get()
        record.request_id = rid or ""  # permet %(request_id)s dans le formatter
        return True


class AggregatorHandler(Handler):
    """During a request (when `agg_buffer` exists), copy the log (as a dict) into the aggregation buffer."""

    def emit(self, record: LogRecord) -> None:
        buf = agg_buffer_var.get()
        if buf is None:
            return
        try:
            log_dict: Dict[str, Any] = {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                ),
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
                "pathname": record.pathname,
                "lineno": record.lineno,
                "funcName": record.funcName,
                "request_id": getattr(record, "request_id", None),
            }
            buf.append(log_dict)
        except Exception:
            pass


def _get_filters() -> dict[str, Any]:
    filter_dict: dict[str, Any] = {
        "add_request_id": {"()": ContextRequestIdFilter},
    }
    if logging_settings.LOKI_LOGGING_ENABLED:
        filter_dict["add_loki_tags"] = {"()": LokiTagsFilter}

    return filter_dict


def _get_handlers() -> dict[str, Any]:
    handlers_dict: dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "std",
            "level": "INFO",
            "filters": ["add_request_id"],
        },
        "access_console": {
            "class": "logging.StreamHandler",
            "formatter": "uvicorn_access",
            "level": "INFO",
            "filters": ["add_request_id"],
        },
        "aggregator": {
            "class": "document_ia_api.core.logging_setup.AggregatorHandler",
            "level": "DEBUG",
            "filters": ["add_request_id"],
        },
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        handlers_dict["loki"] = {
            "()": "document_ia_api.core.logging_setup.build_loki_handler_for_app",
            "level": "INFO",
            "formatter": "std",
            "filters": ["add_request_id", "add_loki_tags"],
        }
        handlers_dict["loki_json"] = {
            "()": "document_ia_api.core.logging_setup.build_loki_handler_for_app",
            "level": "INFO",
            "formatter": "message_only",
            "filters": ["add_loki_tags"],
        }

    return handlers_dict


def _get_loggers() -> dict[str, Any]:
    loggers_dict: dict[str, Any] = {
        "uvicorn.access": {
            "handlers": ["access_console"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "aggregator": {
            "handlers": [],
            "level": "INFO",
            "propagate": False,
        },
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        loggers_dict["uvicorn.access"]["handlers"].append("loki")
        loggers_dict["uvicorn.error"]["handlers"].append("loki")
        loggers_dict["aggregator"]["handlers"].append("loki_json")

    return loggers_dict


def _get_root_logger() -> dict[str, Any]:
    root_logger_dict: dict[str, Any] = {
        "handlers": ["console", "aggregator"],
        "level": "INFO",
    }

    if logging_settings.LOKI_LOGGING_ENABLED:
        root_logger_dict["handlers"].append("loki")

    return root_logger_dict


def setup_logging():
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": _get_filters(),
        "formatters": {
            "std": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(request_id)s - %(message)s",
            },
            "uvicorn_access": {
                "format": "%(asctime)s - uvicorn.access - %(levelname)s - %(message)s",
            },
            "message_only": {"format": "%(message)s"},
        },
        "handlers": _get_handlers(),
        "loggers": _get_loggers(),
        "root": _get_root_logger(),
    }
    dictConfig(config)


# À appeler le plus tôt possible dans ton entrypoint (avant de lancer uvicorn)
