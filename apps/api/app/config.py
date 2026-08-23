"""
Centralized settings, loaded from environment variables (.env in local dev).
Keep every config value here -- no hardcoded connection strings or flags
scattered through the codebase.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql://sih26002:sih26002@localhost:5432/sih26002"
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # data source config -- filled in once §1 access checks confirm the real shape
    cwc_nwdp_base_url: str | None = None
    asdma_base_url: str | None = None

    # object storage (satellite scenes, DEM tiles) -- stub for now
    object_storage_endpoint: str | None = None
    object_storage_bucket: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
