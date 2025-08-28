import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Key for authentication
    api_key: str = os.getenv("API_KEY", "")
    
    # API configuration
    title: str = "Document IA API"
    description: str = "API minimaliste avec authentification API_KEY"
    version: str = "1.0.0"
    
    # Server configuration
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = os.getenv("PORT", 8000)
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
