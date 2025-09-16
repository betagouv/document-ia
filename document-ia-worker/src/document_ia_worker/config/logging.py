from logging.config import dictConfig


def setup_logging():
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "std": {
                    # Ajout du nom du thread
                    "format": "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "std",
                    "level": "INFO",
                },
            },
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
        }
    )
