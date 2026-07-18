from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DUNGEON_", extra="ignore")

    app_name: str = "Lambda MicroVM Dungeon Agent"
    environment: str = "development"
    workspace_dir: Path = Path("/workspace")


@lru_cache
def get_settings() -> Settings:
    return Settings()
