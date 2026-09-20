import os
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = ""
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    mapping_auto_threshold: float = 0.85
    mapping_ambiguity_gap: float = 0.12
    target_max_retries: int = 3
    demo_mode: bool = True
    # Production AI service settings
    ai_provider: str = "ollama"  # Options: ollama, openai, anthropic, fallback
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-haiku-20240307"

    class Config:
        env_prefix = "MIGRATION_"


_root = Path(__file__).resolve().parent.parent
_settings = Settings()

# Use Railway's DATABASE_URL if available, otherwise fallback to SQLite
railway_db_url = os.getenv("DATABASE_URL")  # Railway provides this
if railway_db_url:
    # Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async
    if railway_db_url.startswith("postgres://"):
        railway_db_url = railway_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    _settings.database_url = railway_db_url
elif not _settings.database_url:
    _settings.database_url = f"sqlite+aiosqlite:///{_root / 'migration.db'}"

settings = _settings
