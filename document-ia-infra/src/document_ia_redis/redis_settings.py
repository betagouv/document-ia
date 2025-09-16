import os

from pydantic_settings import BaseSettings


class RedisSettings(BaseSettings):
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "password")

    REDIS_URL: str | None = os.getenv("REDIS_URL")

    EVENT_STREAM_NAME: str = os.getenv("EVENT_STREAM_NAME", "event_stream")
    EVENT_STREAM_EXPIRATION: int = int(os.getenv("EVENT_STREAM_EXPIRATION", 300))
    EVENT_STREAM_MAXLEN: int = int(os.getenv("EVENT_STREAM_MAXLEN", 1000))

    def get_redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL

        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


redis_settings = RedisSettings()
