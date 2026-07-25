from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.search import SearchFilters, SearchService
from research_memory.utils import compact_whitespace, query_terms, truncate


@dataclass(slots=True)
class EvidenceItem:
    label: str
    document_id: int
    title: str
    page_number: int
    text: str
    score: float


@dataclass(slots=True)
class Answer:
    text: str
    evidence: list[EvidenceItem]
    mode: str
    warning: str | None = None


class QuestionAnsweringService:
    def __init__(self, db: Database, search: SearchService, settings: Settings):
        self.db = db
        self.search = search
        self.settings = settings

    async def answer(
        self,
        question: str,
        *,
        document_ids: list[int] | None = None,
        project_id: int | None = None,
        primary_sources_only: bool = False,
    ) -> Answer:
        filters = SearchFilters(project_id=project_id, document_ids=document_ids)
        hits = self.search.search_chunks(question, filters=filters, limit=14)
        if primary_sources_only:
            excluded_types = {"review", "systematic_review", "guideline"}
            retained = []
            for hit in hits:
                row = self.db.fetch_one(
                    "SELECT source_type FROM documents WHERE id = ?", (hit.document_id,)
                )
                if row and row["source_type"] not in excluded_types:
                    retained.append(hit)
            hits = retained

        if not hits:
            return Answer(
                text="I could not find a sufficiently relevant passage in the selected library scope.",
                evidence=[],
                mode="retrieval",
                warning="Broaden the scope or try terms that may appear in the papers.",
            )

        document_ids_for_titles = sorted({hit.document_id for hit in hits})
        placeholders = ",".join("?" for _ in document_ids_for_titles)
        rows = self.db.fetch_all(
            f"SELECT id, title FROM documents WHERE id IN ({placeholders})",
            document_ids_for_titles,
        )
        titles = {int(row["id"]): row["title"] for row in rows}
        evidence = [
            EvidenceItem(
                label=f"S{index}",
                document_id=hit.document_id,
                title=titles.get(hit.document_id, "Untitled article"),
                page_number=hit.page_number,
                text=truncate(hit.text, 1_200),
                score=hit.score,
            )
            for index, hit in enumerate(hits, start=1)
        ]

        if self._llm_configured:
            try:
                generated = await self._llm_answer(question, evidence)
                return Answer(text=generated, evidence=evidence, mode="llm-grounded")
            except Exception as exc:
                extractive = self._extractive_answer(question, evidence)
                return Answer(
                    text=extractive,
                    evidence=evidence,
                    mode="extractive",
                    warning=(
                        "The configured language model could not be reached; an extractive "
                        f"answer was returned instead ({exc.__class__.__name__})."
                    ),
                )

        return Answer(
            text=self._extractive_answer(question, evidence),
            evidence=evidence,
            mode="extractive",
            warning=(
                "No language model is configured. This answer selects relevant source sentences "
                "rather than generating a cross-paper interpretation."
            ),
        )

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self.settings.llm_base_url
            and self.settings.llm_api_key
            and self.settings.llm_model
        )

    def _extractive_answer(self, question: str, evidence: list[EvidenceItem]) -> str:
        terms = set(query_terms(question))
        candidates: list[tuple[float, str, str]] = []
        for item in evidence:
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", compact_whitespace(item.text))
            for sentence in sentences:
                if len(sentence) < 35:
                    continue
                words = set(query_terms(sentence))
                overlap = len(terms & words)
                numerical_bonus = 0.5 if re.search(r"\d", sentence) else 0.0
                score = item.score + overlap * 0.45 + numerical_bonus
                candidates.append((score, sentence, item.label))
        candidates.sort(key=lambda value: value[0], reverse=True)
        selected: list[str] = []
        seen: set[str] = set()
        for _, sentence, label in candidates:
            signature = sentence.lower()[:100]
            if signature in seen:
                continue
            seen.add(signature)
            selected.append(f"{truncate(sentence, 420)} [{label}]")
            if len(selected) == 5:
                break
        if not selected:
            return "The retrieved passages are listed below, but no concise extractive answer was found."
        return "Most relevant directly reported passages:\n\n" + "\n\n".join(selected)

    async def _llm_answer(self, question: str, evidence: list[EvidenceItem]) -> str:
        source_block = "\n\n".join(
            f"[{item.label}] {item.title}, page {item.page_number}\n{item.text}"
            for item in evidence
        )
        system = (
            "You are a literature assistant. Answer only from the supplied sources. "
            "Distinguish directly reported findings from synthesis or interpretation. "
            "Cite every factual sentence with source labels such as [S1] or [S2, S4]. "
            "Preserve exact numbers and units. State explicitly when the sources do not answer "
            "part of the question. Do not invent bibliographic facts."
        )
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"Question:\n{question}\n\nSources:\n{source_block}",
                },
            ],
        }
        base = str(self.settings.llm_base_url).rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()
