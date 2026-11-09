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
    app_port: int = 8903

    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    tavily_api_key: str = ""

    # Dev: set MySQL in repo-root .env. Prod/Docker Compose forces SQLite.
    database_url: str = ""
    request_timeout_seconds: float = 30.0
    max_search_results: int = 5
    cors_origins: str = "http://localhost:7093,http://127.0.0.1:7093"

    max_message_length: int = 1000
    prompt_version: str = "v3"
    # P0 session memory: when false, fall back to single-turn generation.
    session_memory_enabled: bool = True
    context_token_budget: int = 4000
    context_max_turns: int = 6
    # P2: on-demand history summary when older complete turns fall outside the window.
    context_summary_enabled: bool = True
    context_summary_max_chars: int = 800
    # Bound tokens sent to the summary model per request (complete-turn batches).
    context_summary_input_token_budget: int = 2500

    jwt_secret: str = "dev-only-change-me-fridgepilot-jwt"
    jwt_expire_hours: int = 168

    log_level: str = "INFO"
    # Relative to process cwd (usually fridgepilotserver/). Empty = stdout only.
    log_file: str = "logs/fridgepilotserver.log"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
