from __future__ import annotations

import os
import shutil
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

    embedding_backend: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_index_version: str = "bge-small-en-v1.5-f16-v1"
    model_dir: Path | None = None

    max_upload_mb: int = 250
    max_pdf_pages: int = 5_000
    max_ocr_pixels: int = 40_000_000
    chunk_chars: int = 1_600
    chunk_overlap: int = 240
    worker_count: int = 2
    auto_ocr: bool = True
    ocr_language: str = "eng"
    tesseract_path: str | None = None

    ipc_token: str | None = None
    allow_legacy_web: bool = False
    enable_network_metadata: bool = False
    diagnostics_enabled: bool = False

    @field_validator("data_dir", mode="before")
    @classmethod
    def expand_data_dir(cls, value: object) -> Path:
        return Path(str(value)).expanduser().resolve()

    @field_validator("model_dir", mode="before")
    @classmethod
    def expand_model_dir(cls, value: object) -> Path | None:
        if value in (None, ""):
            return None
        return Path(str(value)).expanduser().resolve()

    @field_validator("embedding_backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"hash", "fastembed", "sentence-transformers"}
        if normalized not in allowed:
            raise ValueError(f"embedding_backend must be one of {sorted(allowed)}")
        return normalized

    @property
    def database_path(self) -> Path:
        return self.data_dir / "research_memory.sqlite3"

    @property
    def library_dir(self) -> Path:
        """Legacy managed-library location retained for v0.1 migration."""

        return self.data_dir / "library"

    @property
    def import_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def objects_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def resolved_model_dir(self) -> Path:
        return self.model_dir or self.data_dir / "models"

    @property
    def resolved_tesseract_path(self) -> str | None:
        if self.tesseract_path:
            configured = Path(self.tesseract_path).expanduser()
            if configured.is_file() and os.access(configured, os.X_OK):
                return str(configured.resolve())
            return shutil.which(self.tesseract_path)
        return shutil.which("tesseract")

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.library_dir,
            self.import_dir,
            self.objects_dir,
            self.backups_dir,
            self.exports_dir,
            self.temp_dir,
            self.resolved_model_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
