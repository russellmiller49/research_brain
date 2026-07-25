from __future__ import annotations

from fastapi.testclient import TestClient

from research_memory.config import Settings
from research_memory.main import create_app


def test_core_pages_and_health(tmp_path):
    settings = Settings(data_dir=tmp_path / "web-data")
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        for path in ["/", "/library", "/search", "/import", "/projects", "/topics", "/ask"]:
            response = client.get(path)
            assert response.status_code == 200, path
            assert "Research Memory" in response.text


def test_edit_and_export_routes(tmp_path):
    settings = Settings(data_dir=tmp_path / "export-data")
    app = create_app(settings)
    db = app.state.db
    cursor = db.execute(
        """
        INSERT INTO documents(title, normalized_title, authors, journal, publication_year, doi)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "Initial Article Title",
            "initial article title",
            "Jane Smith",
            "Example Journal",
            2025,
            "10.1000/example",
        ),
    )
    document_id = int(cursor.lastrowid)
    project_cursor = db.execute(
        "INSERT INTO projects(name, project_type) VALUES (?, ?)",
        ("Export Project", "manuscript"),
    )
    project_id = int(project_cursor.lastrowid)
    db.execute(
        "INSERT INTO project_documents(project_id, document_id, status) VALUES (?, ?, ?)",
        (project_id, document_id, "included"),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/documents/{document_id}/update",
            data={
                "title": "Revised Article Title",
                "authors": "Jane Smith",
                "journal": "Example Journal",
                "publication_year": "2025",
                "doi": "10.1000/example",
                "pmid": "12345678",
                "reading_status": "read",
                "importance": "5",
                "why_saved": "Useful endpoint definition",
                "user_summary": "A concise personal summary.",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        assert row["normalized_title"] == "revised article title"
        assert row["reading_status"] == "read"

        bib = client.get(f"/documents/{document_id}/export.bib")
        assert bib.status_code == 200
        assert "Revised Article Title" in bib.text

        ris = client.get(f"/projects/{project_id}/export.ris")
        assert ris.status_code == 200
        assert "TY  - JOUR" in ris.text

        markdown = client.get(f"/projects/{project_id}/export.md")
        assert markdown.status_code == 200
        assert "# Export Project" in markdown.text
