from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.embeddings import HashEmbedder
from research_memory.services.ingest import IngestionService
from research_memory.services.search import SearchService


def make_pdf(path: Path, pages: list[str], *, title: str, author: str = "") -> Path:
    document = fitz.open()
    document.set_metadata({"title": title, "author": author})
    for content in pages:
        page = document.new_page(width=612, height=792)
        page.insert_textbox(
            fitz.Rect(54, 54, 558, 738),
            content,
            fontsize=10,
            fontname="helv",
            lineheight=1.25,
        )
    document.save(path)
    document.close()
    return path


@pytest.fixture
def services(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", chunk_chars=600, chunk_overlap=80)
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    embedder = HashEmbedder(dimension=128)
    ingestion = IngestionService(db, settings, embedder)
    search = SearchService(db, embedder)
    return settings, db, ingestion, search
