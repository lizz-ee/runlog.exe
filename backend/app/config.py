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

    # File Storage
    storage_root: str = "/mnt/projects"  # Root path for project files
    thumbnails_path: str = "./thumbnails"  # Path for generated thumbnails

    # Media Processing
    thumbnail_width: int = 320
    thumbnail_height: int = 180
    supported_video_formats: str = ".mp4,.mov,.avi,.mkv,.webm"
    supported_image_formats: str = ".jpg,.jpeg,.png,.exr,.tif,.tiff"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
