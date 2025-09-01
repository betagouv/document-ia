import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class DatabaseSettings(BaseSettings):
    POSTGRES_DB: str | None = os.getenv("POSTGRES_DB")
    POSTGRES_HOST: str | None = os.getenv("POSTGRES_HOST")
    POSTGRES_PORT: int | None = os.getenv("POSTGRES_PORT")

    POSTGRES_USER: str | None = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD: str | None = os.getenv("POSTGRES_PASSWORD")


class RedisSettings(BaseSettings):
    REDIS_PORT: int | None = os.getenv("REDIS_PORT")


class Settings(DatabaseSettings, RedisSettings):
    pass

# Global settings instance
settings = Settings()
