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

    class Config:
        env_prefix = "MIGRATION_"


_root = Path(__file__).resolve().parent.parent
_settings = Settings()
if not _settings.database_url:
    _settings.database_url = f"sqlite+aiosqlite:///{_root / 'migration.db'}"
settings = _settings
