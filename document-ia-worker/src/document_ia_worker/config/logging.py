from logging.config import dictConfig

from document_ia_infra.core.loki_settings import build_loki_handler, LokiTagsFilter


def build_loki_handler_for_app():
    return build_loki_handler(app_name="document-ia-worker")


def setup_logging():
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "add_loki_tags": {"()": LokiTagsFilter},
            },
            "formatters": {
                "std": {
                    "format": "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s",
                },
                "message_only": {"format": "%(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "std",
                    "level": "INFO",
                },
                "loki": {
                    "()": "document_ia_worker.config.logging.build_loki_handler_for_app",
                    "level": "INFO",
                    "formatter": "std",
                    "filters": ["add_loki_tags"],
                },
                "loki_json": {
                    "()": "document_ia_worker.config.logging.build_loki_handler_for_app",
                    "level": "INFO",
                    "formatter": "message_only",
                    "filters": ["add_loki_tags"],
                },
            },
            "loggers": {
                "aggregator": {
                    "handlers": ["loki_json"],
                    "level": "INFO",
                    "propagate": False,
                }
            },
            "root": {
                "handlers": ["console", "loki"],
                "level": "INFO",
            },
        }
    )
