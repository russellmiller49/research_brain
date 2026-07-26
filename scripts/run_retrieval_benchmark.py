from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.embeddings import create_embedder
from research_memory.services.search import SearchService
from research_memory.utils import build_fts_query, normalize_title


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * value)))
    return ordered[index]


def read_queries(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not str(value.get("query") or "").strip():
            raise ValueError(f"{path}:{line_number} must contain an object with a query")
        records.append(value)
    if not records:
        raise ValueError("The benchmark has no queries")
    return records


def expected_document_id(db: Database, record: dict[str, Any]) -> int:
    expected = record.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError("expected must be an object")
    explicit_id = record.get("expected_article_id") or expected.get("article_id")
    if explicit_id is not None:
        row = db.fetch_one("SELECT id FROM documents WHERE id = ?", (int(explicit_id),))
    elif expected.get("doi"):
        row = db.fetch_one(
            "SELECT id FROM documents WHERE lower(doi) = ? AND deleted_at IS NULL",
            (str(expected["doi"]).strip().lower(),),
        )
    elif expected.get("pmid"):
        row = db.fetch_one(
            "SELECT id FROM documents WHERE pmid = ? AND deleted_at IS NULL",
            (str(expected["pmid"]).strip(),),
        )
    elif expected.get("title"):
        row = db.fetch_one(
            "SELECT id FROM documents WHERE normalized_title = ? AND deleted_at IS NULL",
            (normalize_title(str(expected["title"])),),
        )
    else:
        raise ValueError("Each query needs expected.article_id, DOI, PMID, or title")
    if not row:
        raise ValueError(f"Expected article was not found for query: {record['query']}")
    return int(row["id"])


def fts_only(db: Database, query: str, *, limit: int = 10) -> list[int]:
    try:
        rows = db.fetch_all(
            """
            SELECT f.document_id
            FROM document_chunks_fts f
            JOIN documents d ON d.id = f.document_id
            WHERE document_chunks_fts MATCH ? AND d.deleted_at IS NULL
            ORDER BY bm25(document_chunks_fts, 1.0, 0.0, 0.0, 0.0)
            LIMIT 500
            """,
            (build_fts_query(query),),
        )
    except Exception:
        return []
    output: list[int] = []
    for row in rows:
        document_id = int(row["document_id"])
        if document_id not in output:
            output.append(document_id)
        if len(output) >= limit:
            break
    return output


def provenance_errors(db: Database, results: list[Any]) -> list[str]:
    failures: list[str] = []
    for result in results:
        if result.page_number is None:
            continue
        page = db.fetch_one(
            """
            SELECT text, width, height FROM document_pages
            WHERE document_id = ? AND page_number = ?
            """,
            (result.document_id, result.page_number),
        )
        if not page:
            failures.append(f"{result.document_id}:p{result.page_number}:missing_page")
            continue
        if result.snippet and result.snippet not in page["text"]:
            failures.append(f"{result.document_id}:p{result.page_number}:snippet_not_found")
        for box in result.bounding_boxes:
            coordinates = [box.get(key) for key in ("x0", "y0", "x1", "y1")]
            if not all(isinstance(value, int | float) for value in coordinates):
                failures.append(f"{result.document_id}:p{result.page_number}:invalid_box")
                continue
            x0, y0, x1, y1 = (float(value) for value in coordinates)
            if not (
                0 <= x0 < x1 <= float(page["width"]) + 1
                and 0 <= y0 < y1 <= float(page["height"]) + 1
            ):
                failures.append(f"{result.document_id}:p{result.page_number}:box_out_of_bounds")
    return failures


def hit_at(document_ids: list[int], expected_id: int, cutoff: int) -> bool:
    return expected_id in document_ids[:cutoff]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure half-memory retrieval against a JSONL reference set."
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Fail unless all production retrieval gates are satisfied.",
    )
    args = parser.parse_args()

    settings = Settings(data_dir=args.data_dir)
    settings.ensure_directories()
    db = Database(settings.database_path, settings.backups_dir)
    db.initialize()
    embedder = create_embedder(
        settings.embedding_backend,
        settings.embedding_model,
        settings.resolved_model_dir,
    )
    search = SearchService(db, embedder, settings.data_dir / "indexes")
    records = read_queries(args.queries)

    # Build or map the vector index before measuring warm queries.
    search.search(str(records[0]["query"]), limit=10)

    hybrid_top5 = 0
    hybrid_top10 = 0
    fts_top5_count = 0
    fts_top10_count = 0
    latencies: list[float] = []
    provenance_failures: list[str] = []
    per_query: list[dict[str, Any]] = []
    for record in records:
        query = str(record["query"]).strip()
        expected_id = expected_document_id(db, record)
        started = time.perf_counter()
        results = search.search(query, limit=10)
        latencies.append(time.perf_counter() - started)
        hybrid_ids = [result.document_id for result in results]
        fts_ids = fts_only(db, query, limit=10)
        hit5 = hit_at(hybrid_ids, expected_id, 5)
        hit10 = hit_at(hybrid_ids, expected_id, 10)
        baseline5 = hit_at(fts_ids, expected_id, 5)
        baseline10 = hit_at(fts_ids, expected_id, 10)
        hybrid_top5 += int(hit5)
        hybrid_top10 += int(hit10)
        fts_top5_count += int(baseline5)
        fts_top10_count += int(baseline10)
        failures = provenance_errors(db, results)
        provenance_failures.extend(f"{query[:80]}:{failure}" for failure in failures)
        per_query.append(
            {
                "query": query,
                "expected_article_id": expected_id,
                "hybrid_rank": (
                    hybrid_ids.index(expected_id) + 1 if expected_id in hybrid_ids else None
                ),
                "fts_rank": fts_ids.index(expected_id) + 1 if expected_id in fts_ids else None,
                "latency_seconds": latencies[-1],
            }
        )

    count = len(records)
    metrics = {
        "query_count": count,
        "embedding_backend": embedder.backend_name,
        "embedding_warning": embedder.warning,
        "hybrid_top5": hybrid_top5 / count,
        "hybrid_top10": hybrid_top10 / count,
        "fts_top5": fts_top5_count / count,
        "fts_top10": fts_top10_count / count,
        "top5_improvement_points": (hybrid_top5 - fts_top5_count) / count,
        "warm_search_p50_seconds": statistics.median(latencies),
        "warm_search_p95_seconds": percentile(latencies, 0.95),
        "provenance_failure_count": len(provenance_failures),
    }
    checks = {
        "at_least_300_queries": count >= 300,
        "hybrid_top5_at_least_85_percent": metrics["hybrid_top5"] >= 0.85,
        "hybrid_top10_at_least_95_percent": metrics["hybrid_top10"] >= 0.95,
        "top5_improves_by_15_points": metrics["top5_improvement_points"] >= 0.15,
        "warm_search_p95_under_1_5_seconds": metrics["warm_search_p95_seconds"] < 1.5,
        "all_snippets_and_boxes_have_provenance": not provenance_failures,
        "pinned_semantic_backend_active": embedder.backend_name.startswith("fastembed:")
        and not embedder.warning,
    }
    report = {
        "format": 1,
        "metrics": metrics,
        "checks": checks,
        "passed": all(checks.values()),
        "provenance_failures": provenance_failures[:100],
        "queries": per_query,
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if args.enforce and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
