import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class AppSettings(BaseSettings):
    # API configuration
    APP_VERSION: str = "1.0.0"

    # Server configuration
    SERVER_HOST: str = os.getenv("HOST", "0.0.0.0")
    SERVER_PORT: int = os.getenv("PORT", 8000)


class AuthenticationSettings(BaseSettings):
    # Hardcoded API Key for authentication
    API_KEY: str | None = os.getenv("API_KEY")


class Settings(AppSettings, AuthenticationSettings):
    pass


# Global settings instance
settings = Settings()
