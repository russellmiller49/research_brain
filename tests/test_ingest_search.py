from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from conftest import make_pdf

import research_memory.services.ingest as ingest_module


@pytest.mark.asyncio
async def test_ingest_deduplicates_and_searches_by_detail(tmp_path, services):
    _, db, ingestion, search = services
    paper = make_pdf(
        tmp_path / "robotic.pdf",
        [
            """Robotic Bronchoscopy Diagnostic Performance\nAlice Smith, MD and John Doe, MD\n\nAbstract\nWe conducted a prospective multicenter study of 218 patients with peripheral pulmonary lesions. The primary endpoint was strict diagnostic yield. Navigation success was 94.0%, while strict diagnostic yield was 72.5%. Benign results required 12 months of radiographic follow-up. DOI: 10.1234/example.2026.001\n\nIntroduction\nTechnical success and clinical diagnosis are distinct outcomes.""",
            """Methods\nParticipants without a bronchus sign were not excluded. Severe bleeding occurred in 1.4% of procedures.\n\nLimitations\nThe study was conducted at academic centers and did not include a randomized comparator.""",
        ],
        title="Robotic Bronchoscopy Diagnostic Performance",
        author="Alice Smith; John Doe",
    )
    result = await ingestion.ingest_path(paper)
    assert result.status == "indexed"
    assert result.document_id is not None
    search.invalidate()

    duplicate = await ingestion.ingest_path(paper)
    assert duplicate.status == "duplicate"
    assert duplicate.document_id == result.document_id

    results = search.search("high navigation success but lower strict diagnostic yield")
    assert results
    assert results[0].document_id == result.document_id
    assert results[0].page_number == 1
    assert "full-text term match" in results[0].match_reasons

    numerical = search.search("study with around 200 patients and 1 percent severe bleeding")
    assert numerical
    assert numerical[0].document_id == result.document_id

    file_id = db.scalar(
        "SELECT id FROM document_files WHERE document_id = ?",
        (result.document_id,),
    )
    db.execute(
        "UPDATE document_files SET availability = 'missing' WHERE id = ?",
        (file_id,),
    )
    search.invalidate()
    assert search.search_chunks("strict diagnostic yield") == []
    db.execute(
        "UPDATE document_files SET availability = 'available' WHERE id = ?",
        (file_id,),
    )
    search.invalidate()

    row = db.fetch_one(
        "SELECT doi, page_count, extraction_status FROM documents WHERE id = ?",
        (result.document_id,),
    )
    assert row["doi"] == "10.1234/example.2026.001"
    assert row["page_count"] == 2
    assert row["extraction_status"] == "indexed"

    file_row = db.fetch_one(
        "SELECT id, object_path FROM document_files WHERE document_id = ?",
        (result.document_id,),
    )
    managed = Path(file_row["object_path"])
    managed.write_bytes(b"corrupt managed copy")
    db.execute(
        "UPDATE document_files SET availability = 'missing' WHERE id = ?",
        (file_row["id"],),
    )
    db.execute(
        "UPDATE documents SET review_state = 'missing_source' WHERE id = ?",
        (result.document_id,),
    )
    repaired = await ingestion.ingest_path(paper)
    assert repaired.status == "duplicate"
    assert managed.read_bytes() == paper.read_bytes()
    assert (
        db.scalar(
            "SELECT availability FROM document_files WHERE id = ?",
            (file_row["id"],),
        )
        == "available"
    )
    assert (
        db.scalar(
            "SELECT review_state FROM documents WHERE id = ?",
            (result.document_id,),
        )
        == "ready"
    )


@pytest.mark.asyncio
async def test_recall_requires_meaningful_evidence_and_rejects_nonsense(tmp_path, services):
    _, _, ingestion, search = services
    pregnancy = await ingestion.ingest_path(
        make_pdf(
            tmp_path / "pregnancy.pdf",
            [
                "Flexible Bronchoscopy in Pregnancy\n"
                "Recommendations for performing bronchoscopy safely during pregnancy."
            ],
            title="Flexible Bronchoscopy in Pregnancy",
        )
    )
    await ingestion.ingest_path(
        make_pdf(
            tmp_path / "education.pdf",
            [
                "Experiential Learning\n"
                "People taking ownership over time can learn from perspectives "
                "around the world."
            ],
            title="Experiential Learning",
            author="Momen M. Wahidi",
        )
    )
    await ingestion.ingest_path(
        make_pdf(
            tmp_path / "general.pdf",
            ["Basic Bronchoscopy\nA general introduction to flexible bronchoscopy."],
            title="Basic Bronchoscopy",
        )
    )
    search.invalidate()

    relevant = search.search("the paper about bronchoscopy in pregnancy")
    assert [result.document_id for result in relevant] == [pregnancy.document_id]
    assert [result.document_id for result in search.search("bronchoscopy pregnancy")] == [
        pregnancy.document_id
    ]
    assert search.search("the paper about aliens taking over the world") == []
    assert search.search("the paper about your mom") == []


@pytest.mark.asyncio
async def test_recall_author_intent_uses_article_authors_not_citations(tmp_path, services):
    _, db, ingestion, search = services
    authored = await ingestion.ingest_path(
        make_pdf(
            tmp_path / "authored.pdf",
            [
                "Flexible Bronchoscopy\n"
                "David E. Ost, MD; George A. Eapen, MD\n\n"
                "Abstract\nA review of flexible bronchoscopy techniques."
            ],
            title="Flexible Bronchoscopy",
            author="David E. Ost",
        )
    )
    await ingestion.ingest_path(
        make_pdf(
            tmp_path / "citing.pdf",
            [
                "Unrelated Safety Review\n"
                "Alice Researcher, MD\n\n"
                "Abstract\nA paper about procedural safety.",
                "References\n"
                "Eapen GA, Shah AM, Lei X, et al. Complications and practice patterns. "
                "Chest. 2013;143:1044-1053.",
            ],
            title="Unrelated Safety Review",
            author="Alice Researcher",
        )
    )
    # Reproduce an incomplete imported author field: first-page provenance must
    # still recover the actual author without treating citations as authors.
    db.execute(
        "UPDATE documents SET authors = 'David E. Ost, MD' WHERE id = ?",
        (authored.document_id,),
    )
    search.invalidate()

    results = search.search("paper by Eapen")

    assert [result.document_id for result in results] == [authored.document_id]
    assert results[0].page_number == 1
    assert "first-page author line" in results[0].match_reasons
    assert "eapen" in results[0].snippet.lower()


@pytest.mark.asyncio
async def test_explicit_topic_query_rejects_lists_disclosures_and_references(tmp_path, services):
    _, _, ingestion, search = services
    await ingestion.ingest_path(
        make_pdf(
            tmp_path / "education.pdf",
            [
                "Bronchoscopy Education\n"
                "Abstract\nA review of experiential learning for bronchoscopy trainees.",
                "Recommended annual procedure volumes\n"
                "Thoracoscopy 20, bronchoscopic navigation 20, endobronchial ablation 50, "
                "EBUS 100, tunneled pleural catheter placement 20, percutaneous dilational "
                "tracheostomy 20, image-guided thoracostomy tube placement 20. "
                "Medical residents benefit from spaced education.",
            ],
            title="Bronchoscopy Education",
        )
    )
    await ingestion.ingest_path(
        make_pdf(
            tmp_path / "guideline.pdf",
            [
                "Flexible Bronchoscopy Guideline\n"
                "Abstract\nRecommendations for diagnostic flexible bronchoscopy.",
                "Declaration of interest\n"
                "The author teaches medical thoracoscopy courses sponsored by manufacturers.",
                "References\n"
                "Example A. Medical thoracoscopy in pleural disease. Chest. 2018;154:1-8.",
            ],
            title="Flexible Bronchoscopy Guideline",
        )
    )
    search.invalidate()

    assert search.search("paper about medical thoracoscopy") == []
    assert search.search("medical thoracoscopy") == []


def test_semantic_candidates_require_absolute_and_relative_evidence(services):
    _, _, _, search = services
    search.embedder.backend_name = "fastembed:test"
    rows = [
        (1, 1, 1, 0.82),
        (2, 2, 1, 0.79),
        (3, 3, 1, 0.74),
    ]
    assert search._qualified_semantic_rows(rows) == rows[:2]
    assert search._qualified_semantic_rows([(1, 1, 1, 0.60)]) == []

    search.embedder.backend_name = "hash-v1"
    assert search._qualified_semantic_rows(rows) == []


@pytest.mark.asyncio
async def test_concurrent_identical_imports_reuse_the_winning_asset(
    tmp_path, services, monkeypatch
):
    _, db, ingestion, _ = services
    paper = make_pdf(
        tmp_path / "concurrent.pdf",
        ["Concurrent Import\nAbstract\nThe same immutable paper arrived twice."],
        title="Concurrent Import",
    )
    extraction_barrier = threading.Barrier(2)
    original_extract = ingest_module.extract_pdf

    def synchronized_extract(*args, **kwargs):
        extraction_barrier.wait(timeout=10)
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(ingest_module, "extract_pdf", synchronized_extract)
    results = await asyncio.gather(
        ingestion.ingest_path(paper),
        ingestion.ingest_path(paper),
    )

    assert sorted(result.status for result in results) == ["duplicate", "indexed"]
    assert results[0].document_id == results[1].document_id
    assert db.scalar("SELECT COUNT(*) FROM documents") == 1
    assert db.scalar("SELECT COUNT(*) FROM document_files") == 1


@pytest.mark.asyncio
async def test_reindex_refreshes_local_metadata_but_preserves_user_edits(tmp_path, services):
    _, db, ingestion, _ = services
    paper = make_pdf(
        tmp_path / "metadata-refresh.pdf",
        ["Reliable Local Title\nAbstract\nA local metadata repair fixture."],
        title="Reliable Local Title",
        author="A. Researcher",
    )
    result = await ingestion.ingest_path(paper)
    document_id = int(result.document_id)

    db.execute(
        """
        UPDATE documents
        SET title = 'Incorrect body fragment', normalized_title = 'incorrect body fragment',
            metadata_status = 'local'
        WHERE id = ?
        """,
        (document_id,),
    )
    await ingestion.reindex_document(document_id)
    assert (
        db.scalar("SELECT title FROM documents WHERE id = ?", (document_id,))
        == "Reliable Local Title"
    )

    db.execute(
        """
        UPDATE documents
        SET title = 'My curated title', normalized_title = 'my curated title',
            metadata_status = 'user'
        WHERE id = ?
        """,
        (document_id,),
    )
    await ingestion.reindex_document(document_id)
    assert (
        db.scalar("SELECT title FROM documents WHERE id = ?", (document_id,)) == "My curated title"
    )


@pytest.mark.asyncio
async def test_probable_alternate_version_attaches_to_same_article(tmp_path, services):
    _, db, ingestion, _ = services
    first = make_pdf(
        tmp_path / "first.pdf",
        ["Shared Article Title\nAbstract\nFirst publisher version. DOI: 10.9999/shared.1"],
        title="Shared Article Title",
    )
    second = make_pdf(
        tmp_path / "second.pdf",
        [
            "Shared Article Title\nAbstract\nAccepted manuscript with different bytes. DOI: 10.9999/shared.1"
        ],
        title="Shared Article Title",
    )
    first_result = await ingestion.ingest_path(first)
    second_result = await ingestion.ingest_path(second)
    assert first_result.status == "indexed"
    assert second_result.status == "version"
    assert second_result.document_id == first_result.document_id
    count = db.scalar(
        "SELECT COUNT(*) FROM document_files WHERE document_id = ?", (first_result.document_id,)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_personal_context_participates_in_search(tmp_path, services):
    _, db, ingestion, search = services
    paper = make_pdf(
        tmp_path / "plain.pdf",
        ["Unrelated Formal Title\nAbstract\nA diagnostic methods paper."],
        title="Unrelated Formal Title",
    )
    result = await ingestion.ingest_path(paper)
    db.execute(
        "UPDATE documents SET why_saved = ? WHERE id = ?",
        ("The odd paper with the unexpectedly low pneumothorax rate", result.document_id),
    )
    results = search.search("paper I saved because pneumothorax was unexpectedly low")
    assert results
    assert results[0].document_id == result.document_id
    assert any("saved context" in reason for reason in results[0].match_reasons)
