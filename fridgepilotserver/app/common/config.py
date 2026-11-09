"""应用配置：从仓库根目录 .env 与环境变量加载。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/common/config.py -> parents[3] = 仓库根目录 (FridgePal)
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """FridgePilot 服务端运行时配置。"""

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

    # 开发：在仓库根 .env 配 MySQL；生产/Docker Compose 强制 SQLite
    database_url: str = ""
    request_timeout_seconds: float = 30.0
    max_search_results: int = 5
    cors_origins: str = "http://localhost:7093,http://127.0.0.1:7093"

    max_message_length: int = 1000
    prompt_version: str = "v3"
    # 会话记忆总开关：关闭则退回单轮生成
    session_memory_enabled: bool = True
    context_token_budget: int = 4000
    context_max_turns: int = 6
    # 历史溢出时按需摘要
    context_summary_enabled: bool = True
    context_summary_max_chars: int = 800
    # 单次摘要请求送入模型的 token 上限（完整轮次批次）
    context_summary_input_token_budget: int = 2500

    jwt_secret: str = "dev-only-change-me-fridgepilot-jwt"
    jwt_expire_hours: int = 168

    log_level: str = "INFO"
    # 相对进程 cwd（通常为 fridgepilotserver/）；空字符串表示仅 stdout
    log_file: str = "logs/fridgepilotserver.log"

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的 CORS 源解析为列表。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """缓存的全局 Settings 单例。"""
    return Settings()
