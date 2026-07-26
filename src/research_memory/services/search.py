from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from research_memory.db import Database
from research_memory.services.embeddings import Embedder, blob_to_vector
from research_memory.utils import build_fts_query, query_terms

RRF_K = 60
SEMANTIC_MIN_SIMILARITY = 0.68
SEMANTIC_RELATIVE_WINDOW = 0.04


@dataclass(slots=True)
class SearchFilters:
    year_min: int | None = None
    year_max: int | None = None
    source_type: str | None = None
    reading_status: str | None = None
    project_id: int | None = None
    document_ids: list[int] | None = None


@dataclass(frozen=True, slots=True)
class QueryIntent:
    kind: Literal["general", "author", "topic"]
    value: str


@dataclass(slots=True)
class ChunkHit:
    chunk_id: int
    document_id: int
    file_id: int | None
    page_number: int
    text: str
    bounding_boxes: list[dict[str, Any]]
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
    passage_id: int | None = None
    asset_id: int | None = None
    bounding_boxes: list[dict[str, Any]] = field(default_factory=list)
    relevance: int = 0  # Kept only for v0.1 template compatibility; never displayed.


class VectorIndex:
    """Memory-mapped USearch HNSW with a NumPy fallback for development."""

    def __init__(self, db: Database, embedder: Embedder, index_dir: Path | None = None):
        self.db = db
        self.embedder = embedder
        self.index_dir = index_dir or db.path.parent / "indexes"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", embedder.backend_name)
        self.index_path = self.index_dir / f"{safe_name}-{embedder.dimension}.usearch"
        self.state_name = f"vectors:{embedder.backend_name}:{embedder.dimension}"
        self._signature: tuple[int, int] | None = None
        self._index: Any | None = None
        self._chunk_ids = np.empty((0,), dtype=np.int64)
        self._document_ids = np.empty((0,), dtype=np.int64)
        self._page_numbers = np.empty((0,), dtype=np.int32)
        self._vectors = np.empty((0, embedder.dimension), dtype=np.float32)
        self._using_usearch = False

    def invalidate(self) -> None:
        self._signature = None
        self._index = None

    def _database_signature(self) -> tuple[int, int]:
        row = self.db.fetch_one(
            """
            SELECT COUNT(*) AS count_value, COALESCE(MAX(c.id), 0) AS max_id
            FROM document_chunks c
            JOIN document_files f ON f.id = c.file_id
            WHERE c.embedding_backend = ? AND c.embedding_dim = ?
              AND c.embedding IS NOT NULL AND f.availability = 'available'
            """,
            (self.embedder.backend_name, self.embedder.dimension),
        )
        assert row is not None
        return int(row["count_value"]), int(row["max_id"])

    def ensure_loaded(self) -> None:
        signature = self._database_signature()
        if signature == self._signature:
            return
        version = f"{signature[0]}:{signature[1]}"
        state = self.db.fetch_one(
            "SELECT version FROM index_state WHERE name = ?", (self.state_name,)
        )
        if self.index_path.is_file() and state and state["version"] == version:
            try:
                from usearch.index import Index

                self._index = Index(path=self.index_path, view=True)
                self._using_usearch = True
                self._signature = signature
                return
            except Exception:
                self._index = None

        rows = self.db.fetch_all(
            """
            SELECT c.id, c.document_id, c.page_number, c.embedding
            FROM document_chunks c
            JOIN document_files f ON f.id = c.file_id
            WHERE c.embedding_backend = ? AND c.embedding_dim = ?
              AND c.embedding IS NOT NULL AND f.availability = 'available'
            ORDER BY c.id
            """,
            (self.embedder.backend_name, self.embedder.dimension),
        )
        self._chunk_ids = np.asarray([int(row["id"]) for row in rows], dtype=np.int64)
        self._document_ids = np.asarray([int(row["document_id"]) for row in rows], dtype=np.int64)
        self._page_numbers = np.asarray([int(row["page_number"]) for row in rows], dtype=np.int32)
        self._vectors = (
            np.vstack([blob_to_vector(row["embedding"], self.embedder.dimension) for row in rows])
            if rows
            else np.empty((0, self.embedder.dimension), dtype=np.float32)
        )
        try:
            from usearch.index import Index

            index = Index(
                ndim=self.embedder.dimension,
                metric="cos",
                dtype="f16",
                connectivity=16,
                expansion_add=128,
                expansion_search=96,
            )
            if rows:
                index.add(self._chunk_ids.astype(np.uint64), self._vectors)
            temporary = self.index_path.with_suffix(".usearch.tmp")
            index.save(temporary)
            os.replace(temporary, self.index_path)
            self._index = Index(path=self.index_path, view=True)
            self._using_usearch = True
            self.db.execute(
                """
                INSERT INTO index_state(name, version, item_count, max_item_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    version = excluded.version,
                    item_count = excluded.item_count,
                    max_item_id = excluded.max_item_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.state_name, version, signature[0], signature[1]),
            )
        except Exception:
            self._index = None
            self._using_usearch = False
        self._signature = signature

    def search(
        self,
        query: str,
        *,
        limit: int = 160,
        allowed_document_ids: set[int] | None = None,
    ) -> list[tuple[int, int, int, float]]:
        self.ensure_loaded()
        if self._signature == (0, 0):
            return []
        signature = self._signature or (0, 0)
        query_vector = self.embedder.encode([query])[0]
        if self._using_usearch and self._index is not None:
            candidate_count = min(
                int(signature[0]),
                max(limit if allowed_document_ids is None else limit * 8, 256),
            )
            matches = self._index.search(query_vector, candidate_count)
            keys = [int(value) for value in matches.keys]
            distances = [float(value) for value in matches.distances]
            if not keys:
                return []
            placeholders = ",".join("?" for _ in keys)
            rows = self.db.fetch_all(
                f"""
                SELECT id, document_id, page_number
                FROM document_chunks WHERE id IN ({placeholders})
                """,
                keys,
            )
            lookup = {
                int(row["id"]): (int(row["document_id"]), int(row["page_number"])) for row in rows
            }
            output: list[tuple[int, int, int, float]] = []
            for chunk_id, distance in zip(keys, distances, strict=True):
                location = lookup.get(chunk_id)
                if not location:
                    continue
                document_id, page_number = location
                if allowed_document_ids is not None and document_id not in allowed_document_ids:
                    continue
                output.append((chunk_id, document_id, page_number, max(0.0, 1.0 - distance)))
                if len(output) >= limit:
                    break
            return output

        if not len(self._vectors):
            return []
        scores = self._vectors @ query_vector
        if allowed_document_ids is not None:
            mask = np.isin(
                self._document_ids,
                np.fromiter(allowed_document_ids, dtype=np.int64),
            )
            scores = np.where(mask, scores, -np.inf)
        count = min(limit, len(scores))
        if count <= 0:
            return []
        candidate_indices = np.argpartition(scores, -count)[-count:]
        candidate_indices = candidate_indices[np.argsort(scores[candidate_indices])[::-1]]
        output = []
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
    def __init__(
        self,
        db: Database,
        embedder: Embedder,
        index_dir: Path | None = None,
    ):
        self.db = db
        self.embedder = embedder
        self.vector_index = VectorIndex(db, embedder, index_dir)

    def invalidate(self) -> None:
        self.vector_index.invalidate()

    @classmethod
    def _query_intent(cls, query: str) -> QueryIntent:
        normalized = re.sub(r"\s+", " ", query).strip()
        author_patterns = (
            r"\b(?:paper|article|study|publication)\s+(?:written|authored)\s+by\s+(.+)$",
            r"\b(?:paper|article|study|publication)\s+by\s+(.+)$",
            r"\b(?:written|authored)\s+by\s+(.+)$",
            r"\bauthor(?:ed)?\s*(?:is|:)?\s+(.+)$",
        )
        for pattern in author_patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if not match:
                continue
            value = re.split(
                r"\s+\b(?:about|regarding|concerning|published|from)\b\s+",
                match.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" \t,.;:")
            if query_terms(value):
                return QueryIntent("author", value)

        topic_match = re.search(
            r"\b(?:paper|article|study|publication|review)\s+"
            r"(?:about|on|regarding|concerning)\s+(.+)$",
            normalized,
            re.IGNORECASE,
        )
        if topic_match:
            value = topic_match.group(1).strip(" \t,.;:")
            if query_terms(value):
                return QueryIntent("topic", value)
        raw_terms = query_terms(normalized)
        content_terms = cls._content_terms(normalized)
        if (
            2 <= len(content_terms) <= 4
            and len(content_terms) == len(raw_terms)
            and not any(term.isdigit() for term in content_terms)
        ):
            # A terse noun phrase behaves like a subject query. This prevents the
            # semantic index from returning the nearest domain papers when the
            # requested subject is not actually represented in the library.
            return QueryIntent("topic", normalized)
        return QueryIntent("general", normalized)

    @staticmethod
    def _content_terms(query: str) -> list[str]:
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "with",
            "where",
            "when",
            "that",
            "this",
            "was",
            "were",
            "is",
            "are",
            "of",
            "to",
            "in",
            "on",
            "at",
            "by",
            "as",
            "for",
            "from",
            "my",
            "i",
            "me",
            "mine",
            "you",
            "your",
            "yours",
            "we",
            "our",
            "ours",
            "it",
            "its",
            "paper",
            "study",
            "article",
            "publication",
            "report",
            "about",
            "around",
            "approximately",
            "some",
            "something",
            "one",
            "thing",
            "kind",
            "sort",
            "had",
            "has",
            "have",
            "been",
            "being",
            "because",
            "saved",
            "save",
            "remember",
            "remembered",
            "recall",
            "take",
            "taking",
            "over",
        }
        terms = query_terms(query)
        return [term for term in terms if term not in stopwords]

    @staticmethod
    def _term_matches(term: str, token: str) -> bool:
        if term == token:
            return True
        if len(term) > 3 and term.endswith("s") and term[:-1] == token:
            return True
        return len(token) > 3 and token.endswith("s") and token[:-1] == term

    @classmethod
    def _matched_content_terms(cls, query: str, text: str) -> set[str]:
        terms = cls._content_terms(query)
        tokens = set(query_terms(text or ""))
        return {term for term in terms if any(cls._term_matches(term, token) for token in tokens)}

    @classmethod
    def _coverage(cls, query: str, text: str) -> float:
        terms = cls._content_terms(query)
        if not terms:
            return 0.0
        return len(cls._matched_content_terms(query, text)) / len(terms)

    @classmethod
    def _has_lexical_evidence(cls, query: str, text: str) -> bool:
        terms = cls._content_terms(query)
        if not terms:
            return False
        matched_terms = cls._matched_content_terms(query, text)
        matched = len(matched_terms)
        if len(terms) <= 2:
            lexical_match = matched == len(terms)
        else:
            lexical_match = matched >= max(2, math.ceil(len(terms) * 0.5))
        if lexical_match:
            if len(terms) == 2:
                return cls._terms_within_window(query, text, window=12)
            return True

        percentages, numbers = cls._numeric_values(query)
        if not percentages and not numbers:
            return False
        descriptive_terms = {
            term
            for term in terms
            if not term.isdigit() and term not in {"percent", "percentage", "percentages"}
        }
        matched_descriptive = len(matched_terms & descriptive_terms)
        required_descriptive = max(1, math.ceil(len(descriptive_terms) * 0.5))
        return (
            matched_descriptive >= required_descriptive and cls._numeric_bonus(query, text) >= 0.25
        )

    @classmethod
    def _terms_within_window(cls, query: str, text: str, *, window: int = 18) -> bool:
        terms = cls._content_terms(query)
        if not terms:
            return False
        positions: list[tuple[int, str]] = []
        for index, token in enumerate(query_terms(text or "")):
            for term in terms:
                if cls._term_matches(term, token):
                    positions.append((index, term))
                    break
        if len({term for _, term in positions}) < len(terms):
            return False
        if len(terms) == 1:
            return True

        counts: dict[str, int] = {}
        left = 0
        for right_position, right_term in positions:
            counts[right_term] = counts.get(right_term, 0) + 1
            while len(counts) == len(terms):
                left_position, left_term = positions[left]
                if right_position - left_position <= window:
                    return True
                counts[left_term] -= 1
                if counts[left_term] == 0:
                    del counts[left_term]
                left += 1
        return False

    @staticmethod
    def _looks_like_reference_passage(text: str) -> bool:
        """Identify bibliography text so cited papers do not masquerade as matches."""

        lowered = (text or "").lower()
        compact = re.sub(r"\s+", " ", lowered)
        if re.search(
            r"(?:^|\n)\s*(?:references|bibliography|literature cited)\s*(?:\n|$)",
            lowered[:1_800],
        ):
            return True

        year_count = len(re.findall(r"\b(?:19|20)\d{2}\b", compact))
        et_al_count = len(re.findall(r"\bet\s+al\b", compact))
        citation_number_count = len(re.findall(r"(?:^|\n)\s*(?:\[\d+\]|\d{1,3}\.)\s*", lowered))
        volume_page_count = len(
            re.findall(r"\b\d{4}\s*;\s*\d{1,4}(?:\s*\(\s*\d+\s*\))?\s*:\s*\d+", compact)
        )
        journal_count = len(
            re.findall(
                r"\b(?:chest|thorax|respir(?:ation|atory)|bronchol|"
                r"eur respir j|am j respir|j thorac|lung)\b",
                compact,
            )
        )
        return year_count >= 3 and (
            citation_number_count >= 2
            or volume_page_count >= 2
            or (et_al_count >= 2 and journal_count >= 2)
        )

    @staticmethod
    def _looks_like_disclosure_or_back_matter(text: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").lower())
        return any(
            marker in lowered
            for marker in (
                "declaration of interest",
                "conflicts of interest",
                "conflict of interest",
                "financial interest",
                "role of sponsors",
                "author contributions",
                "acknowledgments",
            )
        )

    @classmethod
    def _looks_like_incidental_topic_passage(cls, text: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").lower())
        return (
            cls._looks_like_reference_passage(text)
            or cls._looks_like_disclosure_or_back_matter(text)
            or any(
                marker in lowered
                for marker in (
                    "recommended annual procedure volumes",
                    "recommended number of procedures",
                    "procedure type case volume",
                    "requisite annual institutional",
                    "fellowship accreditation",
                )
            )
        )

    @classmethod
    def _topic_matches_text(cls, topic: str, text: str, *, window: int = 18) -> bool:
        terms = cls._content_terms(topic)
        if not terms:
            return False
        matched = len(cls._matched_content_terms(topic, text))
        required = len(terms) if len(terms) <= 2 else max(2, math.ceil(len(terms) * 0.75))
        if matched < required:
            return False
        if matched < len(terms):
            reduced_query = " ".join(
                term for term in terms if term in cls._matched_content_terms(topic, text)
            )
            return cls._terms_within_window(reduced_query, text, window=window)
        return cls._terms_within_window(topic, text, window=window)

    @classmethod
    def _topic_has_subject_evidence(
        cls,
        topic: str,
        row: sqlite3.Row,
        hits: list[ChunkHit],
    ) -> bool:
        """Require subject-level evidence for an explicit “paper about …” query."""

        title = row["title"] or ""
        abstract = row["abstract"] or ""
        if cls._topic_matches_text(topic, title, window=12):
            return True
        if (
            abstract
            and not cls._looks_like_incidental_topic_passage(abstract)
            and cls._topic_matches_text(topic, f"{title} {abstract}", window=28)
        ):
            return True

        row_keys = set(row.keys())
        personal_context = " ".join(
            str(row[key] or "")
            for key in ("why_saved", "user_summary", "note_text")
            if key in row_keys
        )
        if personal_context.strip() and cls._topic_matches_text(topic, personal_context, window=28):
            return True

        substantive_hits = [
            hit
            for hit in hits
            if not cls._looks_like_incidental_topic_passage(hit.text)
            and cls._topic_matches_text(topic, hit.text)
        ]
        terms = cls._content_terms(topic)
        if len(terms) >= 2:
            return (
                any(hit.page_number <= 2 for hit in substantive_hits)
                or len({hit.page_number for hit in substantive_hits}) >= 2
            )

        # A single isolated word deep in a PDF is normally incidental. A one-word
        # topic must occur on more than one page unless title/abstract/personal
        # context already established that it is the paper's subject.
        return len({hit.page_number for hit in substantive_hits}) >= 2

    def _qualified_semantic_rows(
        self,
        rows: list[tuple[int, int, int, float]],
    ) -> list[tuple[int, int, int, float]]:
        if not rows or self.embedder.backend_name.startswith("hash"):
            return []
        best_similarity = max(row[3] for row in rows)
        if best_similarity < SEMANTIC_MIN_SIMILARITY:
            return []
        cutoff = max(
            SEMANTIC_MIN_SIMILARITY,
            best_similarity - SEMANTIC_RELATIVE_WINDOW,
        )
        return [row for row in rows if row[3] >= cutoff]

    @staticmethod
    def _numeric_values(text: str) -> tuple[list[float], list[float]]:
        lowered = (text or "").lower()
        word_numbers = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "fifteen": 15,
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
        }
        for word, number in word_numbers.items():
            lowered = re.sub(rf"\b{word}\s+(?=percent\b)", f"{number} ", lowered)
        percent_matches = list(re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:%|percent\b)", lowered))
        percentages = [float(match.group(1)) for match in percent_matches]
        masked = list(lowered)
        for match in percent_matches:
            for index in range(match.start(), match.end()):
                masked[index] = " "
        numbers: list[float] = []
        for match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", "".join(masked)):
            value = float(match.group(1))
            if 1900 <= value <= 2100 and value.is_integer():
                continue
            if math.isfinite(value):
                numbers.append(value)
        return percentages, numbers

    @classmethod
    def _numeric_bonus(cls, query: str, text: str) -> float:
        query_percentages, query_numbers = cls._numeric_values(query)
        if not query_percentages and not query_numbers:
            return 0.0
        text_percentages, text_numbers = cls._numeric_values(text)

        def closeness(query_value: float, candidates: list[float]) -> float:
            if not candidates:
                return 0.0
            if query_value == 0:
                return 1.0 if any(candidate == 0 for candidate in candidates) else 0.0
            scores = []
            for candidate in candidates:
                if candidate == 0:
                    scores.append(0.0)
                    continue
                ratio = max(abs(query_value), abs(candidate)) / min(
                    abs(query_value), abs(candidate)
                )
                scores.append(math.exp(-0.9 * abs(math.log(ratio))))
            return max(scores, default=0.0)

        scores = [closeness(value, text_percentages) for value in query_percentages]
        scores.extend(closeness(value, text_numbers) for value in query_numbers)
        return sum(scores) / len(scores) if scores else 0.0

    def _allowed_document_ids(self, filters: SearchFilters) -> set[int] | None:
        clauses = ["d.deleted_at IS NULL"]
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
        if len(clauses) == 1 and not joins:
            # None means "all active documents" to avoid materializing 10k IDs.
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
        content_terms = self._content_terms(query)
        lexical_rows: list[sqlite3.Row] = []
        if content_terms:
            fts_query = build_fts_query(" ".join(content_terms))
            try:
                lexical_rows = self.db.fetch_all(
                    """
                    SELECT f.chunk_id, f.document_id, f.page_number, c.file_id,
                           c.text, c.bounding_boxes_json,
                           bm25(document_chunks_fts, 1.0, 0.0, 0.0, 0.0) AS fts_rank
                    FROM document_chunks_fts f
                    JOIN document_chunks c ON c.id = f.chunk_id
                    JOIN document_files df ON df.id = c.file_id
                    JOIN documents d ON d.id = f.document_id
                    WHERE document_chunks_fts MATCH ? AND d.deleted_at IS NULL
                      AND df.availability = 'available'
                    ORDER BY fts_rank
                    LIMIT 200
                    """,
                    (fts_query,),
                )
            except Exception:
                lexical_rows = []

        lexical_rank = 0
        for row in lexical_rows:
            document_id = int(row["document_id"])
            if allowed_ids is not None and document_id not in allowed_ids:
                continue
            if self._looks_like_reference_passage(row["text"]):
                continue
            if not self._has_lexical_evidence(query, row["text"]):
                continue
            lexical_rank += 1
            chunk_id = int(row["chunk_id"])
            hits[chunk_id] = ChunkHit(
                chunk_id=chunk_id,
                document_id=document_id,
                file_id=int(row["file_id"]) if row["file_id"] else None,
                page_number=int(row["page_number"]),
                text=row["text"],
                bounding_boxes=json.loads(row["bounding_boxes_json"] or "[]"),
                score=1.0 / (RRF_K + lexical_rank),
                signals=["full-text term match"],
            )

        semantic_rows = self._qualified_semantic_rows(
            self.vector_index.search(query, limit=200, allowed_document_ids=allowed_ids)
        )
        missing_chunk_ids = [chunk_id for chunk_id, *_ in semantic_rows if chunk_id not in hits]
        missing: dict[int, sqlite3.Row] = {}
        if missing_chunk_ids:
            placeholders = ",".join("?" for _ in missing_chunk_ids)
            rows = self.db.fetch_all(
                f"""
                SELECT c.id, c.file_id, c.text, c.bounding_boxes_json
                FROM document_chunks c
                JOIN document_files f ON f.id = c.file_id
                WHERE c.id IN ({placeholders}) AND f.availability = 'available'
                """,
                missing_chunk_ids,
            )
            missing = {int(row["id"]): row for row in rows}
        for semantic_rank, (
            chunk_id,
            document_id,
            page_number,
            _similarity,
        ) in enumerate(semantic_rows, start=1):
            contribution = 1.0 / (RRF_K + semantic_rank)
            if chunk_id in hits:
                hits[chunk_id].score += contribution
                hits[chunk_id].signals.append("local semantic similarity")
                continue
            chunk_row = missing.get(chunk_id)
            if not chunk_row:
                continue
            if self._looks_like_reference_passage(chunk_row["text"]):
                continue
            hits[chunk_id] = ChunkHit(
                chunk_id=chunk_id,
                document_id=document_id,
                file_id=int(chunk_row["file_id"]) if chunk_row["file_id"] else None,
                page_number=page_number,
                text=chunk_row["text"],
                bounding_boxes=json.loads(chunk_row["bounding_boxes_json"] or "[]"),
                score=contribution,
                signals=["local semantic similarity"],
            )

        coverage_ranking = sorted(
            ((self._coverage(query, hit.text), hit.chunk_id) for hit in hits.values()),
            reverse=True,
        )
        for rank, (coverage, chunk_id) in enumerate(coverage_ranking, start=1):
            if coverage <= 0:
                continue
            hits[chunk_id].score += 0.5 / (RRF_K + rank)
            if coverage >= 0.65:
                hits[chunk_id].signals.append("remembered details occur together")

        numeric_ranking = sorted(
            ((self._numeric_bonus(query, hit.text), hit.chunk_id) for hit in hits.values()),
            reverse=True,
        )
        for rank, (numeric, chunk_id) in enumerate(numeric_ranking, start=1):
            if numeric <= 0:
                continue
            hits[chunk_id].score += 1.0 / (RRF_K + rank)
            if numeric >= 0.65:
                hits[chunk_id].signals.append("approximate numerical detail")
        return sorted(hits.values(), key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _first_page_author_zone(text: str, title: str) -> str:
        zone = (text or "")[:5_000]
        if title:
            zone = re.sub(re.escape(title), " ", zone, count=1, flags=re.IGNORECASE)
        section = re.search(
            r"(?im)^\s*(?:abstract|background|introduction|methods?|results?|"
            r"key\s+points?|keywords?)\s*:?\s*$",
            zone,
        )
        if section:
            zone = zone[: section.start()]
        return zone

    @staticmethod
    def _snippet_around_terms(text: str, terms: list[str], *, limit: int = 480) -> str:
        compact = (text or "").strip()
        if len(compact) <= limit:
            return compact
        lowered = compact.lower()
        positions = [lowered.find(term.lower()) for term in terms]
        positions = [position for position in positions if position >= 0]
        if not positions:
            return compact[:limit].strip()
        start = max(0, min(positions) - 120)
        if start:
            next_space = compact.find(" ", start)
            start = next_space + 1 if next_space >= 0 else start
        return compact[start : start + limit].strip()

    def _search_author(
        self,
        author_query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[SearchResult]:
        terms = self._content_terms(author_query)
        if not terms:
            return []
        allowed_ids = self._allowed_document_ids(filters)
        if allowed_ids == set():
            return []

        candidates: set[int] = set()
        author_conditions = " OR ".join("lower(d.authors) LIKE ?" for _ in terms[:8])
        metadata_rows = self.db.fetch_all(
            f"""
            SELECT d.id
            FROM documents d
            WHERE d.deleted_at IS NULL AND ({author_conditions})
            LIMIT 600
            """,
            [f"%{term}%" for term in terms[:8]],
        )
        candidates.update(int(row["id"]) for row in metadata_rows)
        try:
            first_page_rows = self.db.fetch_all(
                """
                SELECT DISTINCT f.document_id
                FROM document_chunks_fts f
                JOIN document_chunks c ON c.id = f.chunk_id
                JOIN document_files df ON df.id = c.file_id
                JOIN documents d ON d.id = f.document_id
                WHERE document_chunks_fts MATCH ? AND c.page_number = 1
                  AND d.deleted_at IS NULL AND df.availability = 'available'
                LIMIT 600
                """,
                (build_fts_query(" ".join(terms)),),
            )
            candidates.update(int(row["document_id"]) for row in first_page_rows)
        except Exception:
            pass
        if allowed_ids is not None:
            candidates.intersection_update(allowed_ids)
        if not candidates:
            return []

        placeholders = ",".join("?" for _ in candidates)
        rows = self.db.fetch_all(
            f"""
            SELECT d.*, COALESCE((
                       SELECT p.text
                       FROM document_pages p
                       WHERE p.document_id = d.id AND p.page_number = 1
                   ), '') AS first_page_text,
                   (
                       SELECT f.id FROM document_files f
                       WHERE f.document_id = d.id AND f.availability = 'available'
                       ORDER BY f.is_primary DESC, f.id LIMIT 1
                   ) AS primary_file_id
            FROM documents d
            WHERE d.id IN ({placeholders}) AND d.deleted_at IS NULL
            """,
            list(candidates),
        )
        chunk_rows = self.db.fetch_all(
            f"""
            SELECT c.id, c.document_id, c.file_id, c.text, c.bounding_boxes_json
            FROM document_chunks c
            JOIN document_files f ON f.id = c.file_id
            WHERE c.document_id IN ({placeholders}) AND c.page_number = 1
              AND f.availability = 'available'
            ORDER BY c.document_id, c.chunk_index
            """,
            list(candidates),
        )
        chunks_by_document: dict[int, list[sqlite3.Row]] = {}
        for chunk_row in chunk_rows:
            chunks_by_document.setdefault(int(chunk_row["document_id"]), []).append(chunk_row)

        normalized_author = " ".join(terms)
        results: list[SearchResult] = []
        for row in rows:
            document_id = int(row["id"])
            metadata_match = self._has_lexical_evidence(author_query, row["authors"] or "")
            author_zone = self._first_page_author_zone(
                row["first_page_text"] or "", row["title"] or ""
            )
            first_page_match = self._has_lexical_evidence(author_query, author_zone)
            if not metadata_match and not first_page_match:
                continue

            document_chunks = chunks_by_document.get(document_id, [])
            chunk = next(
                (
                    candidate
                    for candidate in document_chunks
                    if self._has_lexical_evidence(author_query, candidate["text"] or "")
                ),
                document_chunks[0] if document_chunks else None,
            )
            reasons = []
            score = 0.0
            if metadata_match:
                reasons.append("article author")
                score += 3.0
            if first_page_match:
                reasons.append("first-page author line")
                score += 2.0
            if normalized_author in " ".join(query_terms(row["authors"] or "")):
                score += 0.5

            try:
                keywords = json.loads(row["keywords_json"] or "[]")
            except json.JSONDecodeError:
                keywords = []
            chunk_text = str(chunk["text"] or "") if chunk else ""
            results.append(
                SearchResult(
                    document_id=document_id,
                    title=row["title"],
                    authors=row["authors"],
                    journal=row["journal"],
                    publication_year=row["publication_year"],
                    source_type=row["source_type"],
                    reading_status=row["reading_status"],
                    importance=int(row["importance"] or 0),
                    doi=row["doi"],
                    abstract=row["abstract"],
                    why_saved=row["why_saved"],
                    snippet=self._snippet_around_terms(chunk_text, terms),
                    page_number=1 if chunk else None,
                    score=score,
                    match_reasons=reasons,
                    keywords=keywords,
                    passage_id=int(chunk["id"]) if chunk else None,
                    asset_id=(
                        int(chunk["file_id"])
                        if chunk and chunk["file_id"]
                        else (int(row["primary_file_id"]) if row["primary_file_id"] else None)
                    ),
                    bounding_boxes=(
                        json.loads(chunk["bounding_boxes_json"] or "[]") if chunk else []
                    ),
                )
            )
        results.sort(key=lambda item: (-item.score, item.title.lower(), item.document_id))
        return results[:limit]

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        limit: int = 30,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        filters = filters or SearchFilters()
        intent = self._query_intent(query)
        if intent.kind == "author":
            return self._search_author(intent.value, filters=filters, limit=limit)
        effective_query = intent.value
        allowed_ids = self._allowed_document_ids(filters)
        if allowed_ids == set():
            return []
        chunk_hits = self.search_chunks(
            effective_query,
            filters=filters,
            limit=max(120, limit * 8),
        )
        hits_by_document: dict[int, list[ChunkHit]] = {}
        per_document: dict[int, ChunkHit] = {}
        for hit in chunk_hits:
            hits_by_document.setdefault(hit.document_id, []).append(hit)
            current = per_document.get(hit.document_id)
            if current is None or hit.score > current.score:
                per_document[hit.document_id] = hit

        terms = self._content_terms(effective_query)
        metadata_raw: dict[int, float] = {}
        personal_raw: dict[int, float] = {}
        metadata_reasons: dict[int, list[str]] = {}
        if terms:
            conditions: list[str] = []
            parameters: list[Any] = []
            for term in terms[:12]:
                pattern = f"%{term}%"
                conditions.append(
                    """(
                        lower(d.title) LIKE ? OR lower(d.authors) LIKE ? OR
                        lower(d.journal) LIKE ? OR lower(d.doi) LIKE ? OR
                        lower(d.pmid) LIKE ? OR lower(d.abstract) LIKE ? OR
                        lower(d.why_saved) LIKE ? OR lower(d.user_summary) LIKE ? OR EXISTS (
                            SELECT 1 FROM notes n
                            WHERE n.document_id = d.id AND lower(n.body) LIKE ?
                        )
                    )"""
                )
                parameters.extend([pattern] * 9)
            rows = self.db.fetch_all(
                f"""
                SELECT d.id, d.title, d.authors, d.journal, d.doi, d.pmid,
                       d.abstract, d.why_saved, d.user_summary, COALESCE((
                           SELECT group_concat(n.body, ' ') FROM notes n
                           WHERE n.document_id = d.id
                       ), '') AS note_text
                FROM documents d
                WHERE d.deleted_at IS NULL AND ({" OR ".join(conditions)})
                LIMIT 400
                """,
                parameters,
            )
            query_lower = effective_query.lower()
            for row in rows:
                document_id = int(row["id"])
                if allowed_ids is not None and document_id not in allowed_ids:
                    continue
                bibliographic_score = 0.0
                personal_score = 0.0
                bibliographic_reasons: list[str] = []
                personal_reasons: list[str] = []
                title = row["title"] or ""
                authors = row["authors"] or ""
                journal = row["journal"] or ""
                identifiers = f"{row['doi'] or ''} {row['pmid'] or ''}"
                abstract = row["abstract"] or ""
                why_saved = row["why_saved"] or ""
                user_summary = row["user_summary"] or ""
                note_text = row["note_text"] or ""
                bibliographic_evidence = self._has_lexical_evidence(
                    effective_query,
                    f"{title} {authors} {journal} {identifiers} {abstract}",
                )
                personal_evidence = self._has_lexical_evidence(
                    effective_query,
                    f"{why_saved} {user_summary} {note_text}",
                )
                if query_lower in title.lower():
                    bibliographic_score += 1.0
                    bibliographic_reasons.append("title phrase")
                elif (coverage := self._coverage(effective_query, title)) > 0:
                    bibliographic_score += 0.7 * coverage
                    bibliographic_reasons.append("title terms")
                if (coverage := self._coverage(effective_query, authors)) > 0:
                    bibliographic_score += 0.35 * coverage
                    bibliographic_reasons.append("author")
                if (coverage := self._coverage(effective_query, journal)) > 0:
                    bibliographic_score += 0.3 * coverage
                    bibliographic_reasons.append("journal")
                if (coverage := self._coverage(effective_query, identifiers)) > 0:
                    bibliographic_score += 1.0 * coverage
                    bibliographic_reasons.append("identifier")
                if (coverage := self._coverage(effective_query, abstract)) > 0:
                    bibliographic_score += 0.45 * coverage
                    bibliographic_reasons.append("abstract")
                if (coverage := self._coverage(effective_query, f"{why_saved} {user_summary}")) > 0:
                    personal_score += 1.0 * coverage
                    personal_reasons.append("your saved context")
                if (coverage := self._coverage(effective_query, note_text)) > 0:
                    personal_score += 1.0 * coverage
                    personal_reasons.append("your note")
                reasons: list[str] = []
                if bibliographic_score and bibliographic_evidence:
                    metadata_raw[document_id] = bibliographic_score
                    reasons.extend(bibliographic_reasons)
                if personal_score and personal_evidence:
                    personal_raw[document_id] = personal_score
                    reasons.extend(personal_reasons)
                metadata_reasons[document_id] = reasons

        fused_document_scores: dict[int, float] = {}
        for raw_scores in (metadata_raw, personal_raw):
            ranked = sorted(raw_scores, key=lambda key: (-raw_scores[key], key))
            for rank, document_id in enumerate(ranked, start=1):
                fused_document_scores[document_id] = fused_document_scores.get(
                    document_id, 0.0
                ) + 1.0 / (RRF_K + rank)

        candidate_ids = set(per_document) | set(fused_document_scores)
        if not candidate_ids:
            return []
        placeholders = ",".join("?" for _ in candidate_ids)
        document_rows = self.db.fetch_all(
            f"""
            SELECT d.*, (
                SELECT f.id FROM document_files f
                WHERE f.document_id = d.id AND f.availability = 'available'
                ORDER BY f.is_primary DESC, f.id LIMIT 1
            ) AS primary_file_id,
            COALESCE((
                SELECT group_concat(n.body, ' ') FROM notes n
                WHERE n.document_id = d.id
            ), '') AS note_text
            FROM documents d
            WHERE d.id IN ({placeholders}) AND d.deleted_at IS NULL
            """,
            list(candidate_ids),
        )
        results: list[SearchResult] = []
        for row in document_rows:
            document_id = int(row["id"])
            if intent.kind == "topic" and not self._topic_has_subject_evidence(
                effective_query,
                row,
                hits_by_document.get(document_id, []),
            ):
                continue
            chunk_hit = per_document.get(document_id)
            metadata_score = fused_document_scores.get(document_id, 0.0)
            score = (chunk_hit.score if chunk_hit else 0.0) + metadata_score
            reasons = list(metadata_reasons.get(document_id, []))
            if chunk_hit:
                reasons.extend(chunk_hit.signals)
            reasons = list(dict.fromkeys(reasons))[:5]
            snippet = ""
            if chunk_hit:
                # A literal prefix guarantees the displayed snippet exists on the page.
                snippet = chunk_hit.text[:480].strip()
            else:
                snippet = (row["abstract"] or row["why_saved"] or row["user_summary"] or "")[
                    :480
                ].strip()
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
                    importance=int(row["importance"] or 0),
                    doi=row["doi"],
                    abstract=row["abstract"],
                    why_saved=row["why_saved"],
                    snippet=snippet,
                    page_number=chunk_hit.page_number if chunk_hit else None,
                    score=score,
                    match_reasons=reasons or ["related library metadata"],
                    keywords=keywords,
                    passage_id=chunk_hit.chunk_id if chunk_hit else None,
                    asset_id=(
                        chunk_hit.file_id
                        if chunk_hit and chunk_hit.file_id
                        else (int(row["primary_file_id"]) if row["primary_file_id"] else None)
                    ),
                    bounding_boxes=chunk_hit.bounding_boxes if chunk_hit else [],
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]
