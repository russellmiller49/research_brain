from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="RESEARCH_MEMORY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path.home() / ".research-memory")
    host: str = "127.0.0.1"
    port: int = 8765
    enable_crossref: bool = False
    crossref_mailto: str | None = None

    embedding_backend: str = "hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    max_upload_mb: int = 250
    chunk_chars: int = 1_600
    chunk_overlap: int = 240

    @field_validator("data_dir", mode="before")
    @classmethod
    def expand_data_dir(cls, value: object) -> Path:
        return Path(str(value)).expanduser().resolve()

    @field_validator("embedding_backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"hash", "sentence-transformers"}
        if normalized not in allowed:
            raise ValueError(f"embedding_backend must be one of {sorted(allowed)}")
        return normalized

    @property
    def database_path(self) -> Path:
        return self.data_dir / "research_memory.sqlite3"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def import_dir(self) -> Path:
        return self.data_dir / "imports"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.import_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
