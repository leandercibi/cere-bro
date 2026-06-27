"""Application configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings sourced from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: int = Field(default=0, alias="TELEGRAM_ALLOWED_USER_ID")

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    llm_model: str = Field(default="deepseek/deepseek-chat", alias="LLM_MODEL")

    brave_search_api_key: str = Field(default="", alias="BRAVE_SEARCH_API_KEY")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    hevy_api_key: str = Field(default="", alias="HEVY_API_KEY")
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")

    db_path: Path = Field(default=Path("./data/cerebro.sqlite"), alias="DB_PATH")
    vault_root: Path = Field(default=Path("./vault"), alias="VAULT_ROOT")

    timezone: str = Field(default="Asia/Kolkata", alias="TIMEZONE")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
