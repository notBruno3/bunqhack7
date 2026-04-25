from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    hume_api_key: str = ""
    google_api_key: str = ""

    mock_mode: bool = True
    db_url: str = "sqlite:///./consent.db"
    port: int = 8000

    claude_model: str = "claude-sonnet-4-6"
    # Phase 2 fix: Live preview ID isn't valid on one-shot generate_content.
    # `gemini-flash-latest` resolves to the current GA Flash multimodal model
    # — verified 2026-04-25 against the live API. Swap to `gemini-2.5-flash`
    # if the alias ever resolves to a model with regression in vision quality.
    gemini_model: str = "gemini-flash-latest"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
