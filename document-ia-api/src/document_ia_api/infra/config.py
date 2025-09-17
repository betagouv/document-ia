import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Application settings
    AUTO_MIGRATE: bool = os.getenv("AUTO_MIGRATE", "true").lower() == "true"

    # Rate limiting configuration
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "300")
    )
    RATE_LIMIT_REQUESTS_PER_DAY: int = int(
        os.getenv("RATE_LIMIT_REQUESTS_PER_DAY", "5000")
    )


# Global settings instance
settings = Settings()
