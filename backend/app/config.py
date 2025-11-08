"""
Application configuration and settings
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Configuration
    api_host: str = "localhost"
    api_port: int = 8000
    debug: bool = True

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database
    database_url: str = "sqlite:///./scian.db"

    # Anthropic Claude
    anthropic_api_key: str = ""

    # Social Media APIs
    instagram_client_id: str = ""
    instagram_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
