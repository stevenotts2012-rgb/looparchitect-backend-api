from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "production"
    # Override in production with a restrictive list of allowed origins
    allowed_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"


settings = Settings()
