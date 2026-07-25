from __future__ import annotations

import pytest

from conftest import make_pdf
from research_memory.services.qna import QuestionAnsweringService


@pytest.mark.asyncio
async def test_ingest_deduplicates_and_searches_by_detail(tmp_path, services):
    settings, db, ingestion, search = services
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

    row = db.fetch_one("SELECT doi, page_count, extraction_status FROM documents WHERE id = ?", (result.document_id,))
    assert row["doi"] == "10.1234/example.2026.001"
    assert row["page_count"] == 2
    assert row["extraction_status"] == "indexed"


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
        ["Shared Article Title\nAbstract\nAccepted manuscript with different bytes. DOI: 10.9999/shared.1"],
        title="Shared Article Title",
    )
    first_result = await ingestion.ingest_path(first)
    second_result = await ingestion.ingest_path(second)
    assert first_result.status == "indexed"
    assert second_result.status == "version"
    assert second_result.document_id == first_result.document_id
    count = db.scalar("SELECT COUNT(*) FROM document_files WHERE document_id = ?", (first_result.document_id,))
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


@pytest.mark.asyncio
async def test_extractively_answers_with_page_provenance(tmp_path, services):
    settings, db, ingestion, search = services
    paper = make_pdf(
        tmp_path / "answer.pdf",
        [
            "Outcome Definition Study\nAbstract\nDiagnostic yield was defined as malignant pathology or a benign diagnosis confirmed by 12 months of imaging follow-up. The observed diagnostic yield was 78%."
        ],
        title="Outcome Definition Study",
    )
    result = await ingestion.ingest_path(paper)
    search.invalidate()
    qa = QuestionAnsweringService(db, search, settings)
    answer = await qa.answer("How was diagnostic yield defined?")
    assert answer.evidence
    assert answer.evidence[0].document_id == result.document_id
    assert answer.evidence[0].page_number == 1
    assert "[S" in answer.text
    assert answer.mode == "extractive"
