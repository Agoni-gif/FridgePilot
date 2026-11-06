from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/common/config.py -> parents[3] = project root (FridgePal)
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    tavily_api_key: str = ""

    database_url: str = "sqlite:///./data/fridgepilot.db"
    request_timeout_seconds: float = 30.0
    max_search_results: int = 5
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_message_length: int = 1000
    prompt_version: str = "v2"

    log_level: str = "INFO"
    # Relative to process cwd (usually fridgepilotserver/). Empty = stdout only.
    log_file: str = "logs/fridgepilotserver.log"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
