from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    hume_api_key: str = ""
    google_api_key: str = ""

    mock_mode: bool = True
    db_url: str = "sqlite:///./consent.db"
    port: int = 8000

    claude_model: str = "claude-sonnet-4-6"
    gemini_model: str = "gemini-3.1-flash-live-preview"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
