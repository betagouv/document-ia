from contextvars import ContextVar
from datetime import datetime, timezone
from logging import Filter, LogRecord, Handler
from logging.config import dictConfig
from typing import Optional, Any, Dict, List

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
agg_buffer_var: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "agg_buffer", default=None
)


class ContextRequestIdFilter(Filter):
    """Injecte request_id in every LogRecord if present inside contextvar."""

    def filter(self, record: LogRecord) -> bool:
        rid = request_id_var.get()
        record.request_id = rid or ""  # permet %(request_id)s dans le formatter
        return True


class AggregatorHandler(Handler):
    """
    Handler global qui, pour chaque LogRecord, si on est dans une requête (agg_buffer existe),
    copie le log transformé en dict dans le buffer d'agrégation.
    """

    def emit(self, record: LogRecord) -> None:
        buf = agg_buffer_var.get()
        if buf is None:
            return  # hors requête, on ne collecte pas
        try:
            log_dict: Dict[str, Any] = {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat()
                + "Z",
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage(),
                "pathname": record.pathname,
                "lineno": record.lineno,
                "funcName": record.funcName,
                "request_id": getattr(record, "request_id", None),
                # Tu peux ajouter d'autres champs utiles :
                # "extra": getattr(record, "extra", None),
            }
            buf.append(log_dict)
        except Exception:
            # On n'écrase pas la stack si la collecte échoue
            pass


def setup_logging():
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"add_request_id": {"()": ContextRequestIdFilter}},
            "formatters": {
                "std": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(request_id)s - %(message)s",
                },
                "uvicorn_access": {
                    "format": "%(asctime)s - uvicorn.access - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
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
            },
            "loggers": {
                "uvicorn.access": {
                    "handlers": ["access_console"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["console", "aggregator"],
                "level": "INFO",
            },
        }
    )


# À appeler le plus tôt possible dans ton entrypoint (avant de lancer uvicorn)
