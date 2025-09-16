from logging.config import dictConfig


def setup_logging():
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "std": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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
                },
                "access_console": {
                    "class": "logging.StreamHandler",
                    "formatter": "uvicorn_access",
                    "level": "INFO",
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
                "handlers": ["console"],
                "level": "INFO",
            },
        }
    )


# À appeler le plus tôt possible dans ton entrypoint (avant de lancer uvicorn)
