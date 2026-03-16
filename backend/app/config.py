from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./runlog.db"
    media_upload_dir: str = "media_uploads"

    class Config:
        env_file = ".env"


settings = Settings()
