from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.embeddings import HashEmbedder
from research_memory.services.ingest import IngestionService
from research_memory.services.search import SearchService


def make_pdf(path: Path, pages: list[str], *, title: str, author: str = "") -> Path:
    document = Canvas(str(path), pagesize=(612, 792))
    document.setTitle(title)
    document.setAuthor(author)
    for content in pages:
        text = document.beginText(54, 738)
        text.setFont("Helvetica", 10)
        text.setLeading(13)
        for paragraph in content.splitlines():
            if not paragraph:
                text.textLine("")
                continue
            for line in textwrap.wrap(paragraph, width=92):
                text.textLine(line)
        document.drawText(text)
        document.showPage()
    document.save()
    return path


@pytest.fixture
def services(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        chunk_chars=600,
        chunk_overlap=80,
        auto_ocr=False,
    )
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    embedder = HashEmbedder(dimension=128)
    ingestion = IngestionService(db, settings, embedder)
    search = SearchService(db, embedder)
    return settings, db, ingestion, search
