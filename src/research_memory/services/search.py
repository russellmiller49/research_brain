from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from research_memory.db import Database
from research_memory.services.embeddings import Embedder, blob_to_vector
from research_memory.utils import build_fts_query, compact_whitespace, query_terms, truncate


@dataclass(slots=True)
class SearchFilters:
    year_min: int | None = None
    year_max: int | None = None
    source_type: str | None = None
    reading_status: str | None = None
    project_id: int | None = None
    document_ids: list[int] | None = None


@dataclass(slots=True)
class ChunkHit:
    chunk_id: int
    document_id: int
    page_number: int
    text: str
    score: float
    signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchResult:
    document_id: int
    title: str
    authors: str
    journal: str
    publication_year: int | None
    source_type: str
    reading_status: str
    importance: int
    doi: str
    abstract: str
    why_saved: str
    snippet: str
    page_number: int | None
    score: float
    match_reasons: list[str]
    keywords: list[str]
    relevance: int = 0


class VectorIndex:
    """In-memory vector matrix backed by persisted SQLite blobs."""

    def __init__(self, db: Database, embedder: Embedder):
        self.db = db
        self.embedder = embedder
        self._signature: tuple[int, int] | None = None
        self._chunk_ids = np.empty((0,), dtype=np.int64)
        self._document_ids = np.empty((0,), dtype=np.int64)
        self._page_numbers = np.empty((0,), dtype=np.int32)
        self._vectors = np.empty((0, embedder.dimension), dtype=np.float32)

    def invalidate(self) -> None:
        self._signature = None

    def _database_signature(self) -> tuple[int, int]:
        row = self.db.fetch_one(
            """
            SELECT COUNT(*) AS count_value, COALESCE(MAX(id), 0) AS max_id
            FROM document_chunks
            WHERE embedding_backend = ? AND embedding_dim = ?
            """,
            (self.embedder.backend_name, self.embedder.dimension),
        )
        return int(row["count_value"]), int(row["max_id"])

    def ensure_loaded(self) -> None:
        signature = self._database_signature()
        if signature == self._signature:
            return
        rows = self.db.fetch_all(
            """
            SELECT id, document_id, page_number, embedding
            FROM document_chunks
            WHERE embedding_backend = ? AND embedding_dim = ? AND embedding IS NOT NULL
            ORDER BY id
            """,
            (self.embedder.backend_name, self.embedder.dimension),
        )
        self._chunk_ids = np.asarray([int(row["id"]) for row in rows], dtype=np.int64)
        self._document_ids = np.asarray(
            [int(row["document_id"]) for row in rows], dtype=np.int64
        )
        self._page_numbers = np.asarray(
            [int(row["page_number"]) for row in rows], dtype=np.int32
        )
        if rows:
            self._vectors = np.vstack(
                [blob_to_vector(row["embedding"], self.embedder.dimension) for row in rows]
            )
        else:
            self._vectors = np.empty((0, self.embedder.dimension), dtype=np.float32)
        self._signature = signature

    def search(
        self,
        query: str,
        *,
        limit: int = 80,
        allowed_document_ids: set[int] | None = None,
    ) -> list[tuple[int, int, int, float]]:
        self.ensure_loaded()
        if not len(self._vectors):
            return []
        query_vector = self.embedder.encode([query])[0]
        scores = self._vectors @ query_vector
        if allowed_document_ids is not None:
            mask = np.isin(self._document_ids, np.fromiter(allowed_document_ids, dtype=np.int64))
            scores = np.where(mask, scores, -np.inf)
        count = min(limit, len(scores))
        if count <= 0:
            return []
        candidate_indices = np.argpartition(scores, -count)[-count:]
        candidate_indices = candidate_indices[np.argsort(scores[candidate_indices])[::-1]]
        output: list[tuple[int, int, int, float]] = []
        for index in candidate_indices:
            score = float(scores[index])
            if not np.isfinite(score) or score <= 0:
                continue
            output.append(
                (
                    int(self._chunk_ids[index]),
                    int(self._document_ids[index]),
                    int(self._page_numbers[index]),
                    score,
                )
            )
        return output


class SearchService:
    def __init__(self, db: Database, embedder: Embedder):
        self.db = db
        self.embedder = embedder
        self.vector_index = VectorIndex(db, embedder)

    def invalidate(self) -> None:
        self.vector_index.invalidate()

    @staticmethod
    def _content_terms(query: str) -> list[str]:
        stopwords = {
            "the", "a", "an", "and", "or", "but", "with", "where", "when",
            "that", "this", "was", "were", "is", "are", "of", "to", "in",
            "for", "from", "my", "i", "paper", "study", "article", "about",
            "around", "approximately", "some", "something", "had", "has", "have",
        }
        terms = query_terms(query)
        filtered = [term for term in terms if term not in stopwords and (len(term) > 2 or term.isdigit())]
        return filtered or terms

    @classmethod
    def _coverage(cls, query: str, text: str) -> float:
        terms = cls._content_terms(query)
        if not terms:
            return 0.0
        lowered = (text or "").lower()
        return sum(1 for term in terms if term in lowered) / len(terms)

    @classmethod
    def _ordered_phrase_bonus(cls, query: str, text: str) -> float:
        terms = cls._content_terms(query)
        if len(terms) < 2:
            return 0.0
        lowered = (text or "").lower()
        bigrams = [f"{terms[index]} {terms[index + 1]}" for index in range(len(terms) - 1)]
        trigrams = [
            f"{terms[index]} {terms[index + 1]} {terms[index + 2]}"
            for index in range(len(terms) - 2)
        ]
        return min(0.18, sum(0.035 for phrase in bigrams if phrase in lowered) + sum(0.06 for phrase in trigrams if phrase in lowered))

    @staticmethod
    def _numeric_values(text: str) -> tuple[list[float], list[float]]:
        import math
        import re

        lowered = (text or "").lower()
        word_numbers = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
            "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        }
        for word, number in word_numbers.items():
            lowered = re.sub(rf"\b{word}\s+(?=percent\b)", f"{number} ", lowered)

        percent_matches = list(
            re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", lowered)
        )
        percentages = [float(match.group(1)) for match in percent_matches]
        masked = list(lowered)
        for match in percent_matches:
            for index in range(match.start(), match.end()):
                masked[index] = " "
        remaining = "".join(masked)
        numbers: list[float] = []
        for match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", remaining):
            value = float(match.group(1))
            if 1900 <= value <= 2100 and value.is_integer():
                continue
            if math.isfinite(value):
                numbers.append(value)
        return percentages, numbers

    @classmethod
    def _numeric_bonus(cls, query: str, text: str) -> float:
        import math

        query_percentages, query_numbers = cls._numeric_values(query)
        if not query_percentages and not query_numbers:
            return 0.0
        text_percentages, text_numbers = cls._numeric_values(text)

        def closeness(query_value: float, candidates: list[float]) -> float:
            if not candidates:
                return 0.0
            if query_value == 0:
                return 1.0 if any(candidate == 0 for candidate in candidates) else 0.0
            values = []
            for candidate in candidates:
                if candidate == 0:
                    values.append(0.0)
                    continue
                ratio = max(abs(query_value), abs(candidate)) / min(abs(query_value), abs(candidate))
                values.append(math.exp(-0.9 * abs(math.log(ratio))))
            return max(values, default=0.0)

        scores = [closeness(value, text_percentages) for value in query_percentages]
        scores.extend(closeness(value, text_numbers) for value in query_numbers)
        if not scores:
            return 0.0
        strong = sum(1 for score in scores if score >= 0.65)
        bonus = 0.20 * sum(scores) + (0.07 if strong == len(scores) and strong > 1 else 0.0)
        return min(0.48, bonus)

    def _allowed_document_ids(self, filters: SearchFilters) -> set[int] | None:
        clauses = ["1 = 1"]
        parameters: list[Any] = []
        joins = ""
        if filters.project_id is not None:
            joins += " JOIN project_documents pd ON pd.document_id = d.id "
            clauses.append("pd.project_id = ?")
            parameters.append(filters.project_id)
        if filters.year_min is not None:
            clauses.append("d.publication_year >= ?")
            parameters.append(filters.year_min)
        if filters.year_max is not None:
            clauses.append("d.publication_year <= ?")
            parameters.append(filters.year_max)
        if filters.source_type:
            clauses.append("d.source_type = ?")
            parameters.append(filters.source_type)
        if filters.reading_status:
            clauses.append("d.reading_status = ?")
            parameters.append(filters.reading_status)
        if filters.document_ids is not None:
            if not filters.document_ids:
                return set()
            placeholders = ",".join("?" for _ in filters.document_ids)
            clauses.append(f"d.id IN ({placeholders})")
            parameters.extend(filters.document_ids)

        if clauses == ["1 = 1"] and not joins:
            return None
        rows = self.db.fetch_all(
            f"SELECT DISTINCT d.id FROM documents d {joins} WHERE {' AND '.join(clauses)}",
            parameters,
        )
        return {int(row["id"]) for row in rows}

    def search_chunks(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 20,
    ) -> list[ChunkHit]:
        filters = filters or SearchFilters()
        allowed_ids = self._allowed_document_ids(filters)
        if allowed_ids == set():
            return []

        hits: dict[int, ChunkHit] = {}
        fts_query = build_fts_query(query)
        try:
            lexical_rows = self.db.fetch_all(
                """
                SELECT chunk_id, document_id, page_number, text,
                       bm25(document_chunks_fts, 1.0, 0.0, 0.0, 0.0) AS fts_rank
                FROM document_chunks_fts
                WHERE document_chunks_fts MATCH ?
                ORDER BY fts_rank
                LIMIT 160
                """,
                (fts_query,),
            )
        except Exception:
            lexical_rows = []

        lexical_position = 0
        for row in lexical_rows:
            document_id = int(row["document_id"])
            if allowed_ids is not None and document_id not in allowed_ids:
                continue
            lexical_position += 1
            score = 0.62 * (1.0 / (1.0 + 0.035 * lexical_position))
            chunk_id = int(row["chunk_id"])
            hits[chunk_id] = ChunkHit(
                chunk_id=chunk_id,
                document_id=document_id,
                page_number=int(row["page_number"]),
                text=row["text"],
                score=score,
                signals=["full-text term match"],
            )

        semantic_rows = self.vector_index.search(
            query, limit=160, allowed_document_ids=allowed_ids
        )
        missing_chunk_ids = [chunk_id for chunk_id, *_ in semantic_rows if chunk_id not in hits]
        missing_text: dict[int, Any] = {}
        if missing_chunk_ids:
            placeholders = ",".join("?" for _ in missing_chunk_ids)
            rows = self.db.fetch_all(
                f"SELECT id, text FROM document_chunks WHERE id IN ({placeholders})",
                missing_chunk_ids,
            )
            missing_text = {int(row["id"]): row["text"] for row in rows}

        for position, (chunk_id, document_id, page_number, similarity) in enumerate(
            semantic_rows, start=1
        ):
            semantic_score = 0.38 * max(0.0, min(1.0, similarity))
            if chunk_id in hits:
                hits[chunk_id].score += semantic_score
                hits[chunk_id].signals.append("local similarity match")
            else:
                hits[chunk_id] = ChunkHit(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    page_number=page_number,
                    text=missing_text.get(chunk_id, ""),
                    score=semantic_score * (1.0 / (1.0 + 0.01 * position)),
                    signals=["local similarity match"],
                )

        for hit in hits.values():
            coverage = self._coverage(query, hit.text)
            numeric_bonus = self._numeric_bonus(query, hit.text)
            hit.score += 0.32 * coverage + self._ordered_phrase_bonus(query, hit.text) + numeric_bonus
            if coverage >= 0.65:
                hit.signals.append("most remembered details occur together")
            if numeric_bonus >= 0.10:
                hit.signals.append("approximate numerical details match")

        return sorted(hits.values(), key=lambda item: item.score, reverse=True)[:limit]

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 30,
    ) -> list[SearchResult]:
        filters = filters or SearchFilters()
        allowed_ids = self._allowed_document_ids(filters)
        if allowed_ids == set():
            return []

        chunk_hits = self.search_chunks(query, filters=filters, limit=max(100, limit * 5))
        per_document: dict[int, ChunkHit] = {}
        document_hit_texts: dict[int, list[str]] = {}
        for hit in chunk_hits:
            current = per_document.get(hit.document_id)
            if current is None or hit.score > current.score:
                per_document[hit.document_id] = hit
            texts = document_hit_texts.setdefault(hit.document_id, [])
            if len(texts) < 6:
                texts.append(hit.text)

        terms = query_terms(query)
        metadata_scores: dict[int, tuple[float, list[str]]] = {}
        if terms:
            conditions: list[str] = []
            parameters: list[Any] = []
            for term in terms[:12]:
                pattern = f"%{term}%"
                conditions.append(
                    """(
                        lower(d.title) LIKE ? OR lower(d.authors) LIKE ? OR
                        lower(d.abstract) LIKE ? OR lower(d.why_saved) LIKE ? OR
                        lower(d.user_summary) LIKE ? OR EXISTS (
                            SELECT 1 FROM notes n
                            WHERE n.document_id = d.id AND lower(n.body) LIKE ?
                        )
                    )"""
                )
                parameters.extend([pattern] * 6)
            rows = self.db.fetch_all(
                f"""
                SELECT d.id, d.title, d.authors, d.abstract, d.why_saved, d.user_summary,
                       COALESCE((
                           SELECT group_concat(n.body, ' ') FROM notes n
                           WHERE n.document_id = d.id
                       ), '') AS note_text
                FROM documents d
                WHERE {' OR '.join(conditions)}
                LIMIT 300
                """,
                parameters,
            )
            query_lower = query.lower()
            for row in rows:
                document_id = int(row["id"])
                if allowed_ids is not None and document_id not in allowed_ids:
                    continue
                score = 0.0
                reasons: list[str] = []
                title = row["title"] or ""
                authors = row["authors"] or ""
                abstract = row["abstract"] or ""
                why_saved = row["why_saved"] or ""
                user_summary = row["user_summary"] or ""
                note_text = row["note_text"] or ""
                title_coverage = self._coverage(query, title)
                author_coverage = self._coverage(query, authors)
                abstract_coverage = self._coverage(query, abstract)
                personal_coverage = self._coverage(query, f"{why_saved} {user_summary}")
                note_coverage = self._coverage(query, note_text)
                if query_lower and query_lower in title.lower():
                    score += 0.34
                    reasons.append("title phrase match")
                elif title_coverage > 0:
                    score += 0.22 * title_coverage
                    reasons.append("title term match")
                if author_coverage > 0:
                    score += 0.07 * author_coverage
                    reasons.append("author match")
                if abstract_coverage > 0:
                    score += 0.14 * abstract_coverage
                    reasons.append("abstract match")
                if personal_coverage > 0:
                    score += 0.30 * personal_coverage
                    reasons.append("your saved context or summary matches")
                if note_coverage > 0:
                    score += 0.30 * note_coverage
                    reasons.append("your note matches")
                metadata_scores[document_id] = (score, reasons)

        candidate_ids = set(per_document) | set(metadata_scores)
        if not candidate_ids:
            return []
        placeholders = ",".join("?" for _ in candidate_ids)
        document_rows = self.db.fetch_all(
            f"SELECT * FROM documents WHERE id IN ({placeholders})", list(candidate_ids)
        )

        results: list[SearchResult] = []
        for row in document_rows:
            document_id = int(row["id"])
            chunk_hit = per_document.get(document_id)
            metadata_score, metadata_reasons = metadata_scores.get(document_id, (0.0, []))
            score = (chunk_hit.score if chunk_hit else 0.0) + metadata_score
            importance = int(row["importance"] or 0)
            score += importance * 0.01
            reasons = list(metadata_reasons)
            article_numeric_bonus = self._numeric_bonus(
                query, " ".join(document_hit_texts.get(document_id, []))
            )
            if article_numeric_bonus > 0:
                score += 0.60 * article_numeric_bonus
            if article_numeric_bonus >= 0.18:
                reasons.append("multiple approximate numerical details match")
            if chunk_hit:
                reasons.extend(chunk_hit.signals)
            reasons = list(dict.fromkeys(reasons))[:5]
            snippet = (
                truncate(chunk_hit.text, 480)
                if chunk_hit
                else truncate(row["abstract"] or row["why_saved"] or row["user_summary"], 480)
            )
            try:
                keywords = json.loads(row["keywords_json"] or "[]")
            except json.JSONDecodeError:
                keywords = []
            results.append(
                SearchResult(
                    document_id=document_id,
                    title=row["title"],
                    authors=row["authors"],
                    journal=row["journal"],
                    publication_year=row["publication_year"],
                    source_type=row["source_type"],
                    reading_status=row["reading_status"],
                    importance=importance,
                    doi=row["doi"],
                    abstract=row["abstract"],
                    why_saved=row["why_saved"],
                    snippet=snippet,
                    page_number=chunk_hit.page_number if chunk_hit else None,
                    score=score,
                    match_reasons=reasons or ["related library record"],
                    keywords=keywords,
                    relevance=0,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        if results and results[0].score > 0:
            top_score = results[0].score
            for result in results:
                result.relevance = max(1, min(100, round(100 * result.score / top_score)))
        return results[:limit]
