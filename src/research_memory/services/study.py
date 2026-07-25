from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from research_memory.utils import compact_whitespace, truncate


SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
NUMBER_RE = re.compile(
    r"(?:\bn\s*=\s*\d+[\d,]*\b|\b\d+(?:\.\d+)?\s*%|\b(?:95\s*%\s*)?CI\b|"
    r"\b(?:RR|OR|HR|MD|SMD)\s*[=:]?\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _page_sentences(pages: list[str]) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    for page_number, page in enumerate(pages, start=1):
        text = compact_whitespace(page)
        for sentence in SENTENCE_RE.split(text):
            sentence = compact_whitespace(sentence)
            if 35 <= len(sentence) <= 900:
                output.append((page_number, sentence))
    return output


def _first_matching_sentence(
    sentences: list[tuple[int, str]], patterns: tuple[str, ...]
) -> dict[str, Any] | None:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for page, sentence in sentences:
        if any(pattern.search(sentence) for pattern in compiled):
            return {"value": truncate(sentence, 500), "page": page, "confidence": 0.65}
    return None


def _key_result_sentences(sentences: list[tuple[int, str]]) -> list[dict[str, Any]]:
    candidates: list[tuple[float, int, str]] = []
    result_words = re.compile(
        r"\b(?:resulted|associated|increased|decreased|improved|reduced|sensitivity|specificity|"
        r"mortality|yield|complication|outcome|difference|significant|confidence interval)\b",
        re.IGNORECASE,
    )
    for page, sentence in sentences:
        number_hits = len(NUMBER_RE.findall(sentence))
        if number_hits == 0:
            continue
        score = float(number_hits) + (1.5 if result_words.search(sentence) else 0.0)
        if page <= 2:
            score += 0.4
        candidates.append((score, page, sentence))
    candidates.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for _, page, sentence in candidates:
        normalized = sentence.lower()[:120]
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append({"value": truncate(sentence, 520), "page": page, "confidence": 0.55})
        if len(results) == 4:
            break
    return results


def extract_keywords(title: str, abstract: str, pages: list[str], limit: int = 12) -> list[str]:
    corpus = compact_whitespace(f"{title} {title} {abstract} {' '.join(pages[:3])}").lower()
    tokens = re.findall(r"[a-z][a-z\-]{2,}", corpus)
    tokens = [
        token
        for token in tokens
        if token not in ENGLISH_STOP_WORDS
        and token not in {"study", "results", "methods", "conclusion", "patients", "using"}
    ]
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]


def build_study_card(title: str, abstract: str, pages: list[str], source_type: str) -> dict[str, Any]:
    sentences = _page_sentences(pages)
    card: dict[str, Any] = {
        "article_type": {
            "value": source_type.replace("_", " ").title(),
            "page": 1 if pages else None,
            "confidence": 0.7,
        }
    }

    fields = {
        "study_design": (
            r"\b(?:randomi[sz]ed|prospective|retrospective|cross-sectional|cohort|case-control|"
            r"multicenter|single-center|diagnostic accuracy)\b.{0,180}\b(?:study|trial|analysis)\b",
        ),
        "population": (
            r"\b(?:included|enrolled|recruited|eligible)\b.{0,300}\b(?:patients|participants|subjects)\b",
            r"\b(?:patients|participants)\b.{0,220}\b(?:with|undergoing|diagnosed)\b",
        ),
        "sample_size": (
            r"\b(?:included|enrolled|randomi[sz]ed|analyzed|analysed)\b.{0,140}\b\d+[\d,]*\b",
            r"\bn\s*=\s*\d+[\d,]*\b",
        ),
        "primary_endpoint": (
            r"\bprimary (?:outcome|endpoint|end point)\b",
            r"\bmain outcome measure\b",
        ),
        "follow_up": (
            r"\b(?:follow-up|follow up|followed)\b.{0,220}\b(?:day|days|week|weeks|month|months|year|years)\b",
        ),
        "limitations": (
            r"\b(?:limitations?|strengths and limitations)\b",
            r"\bthis study (?:has|had) several limitations\b",
        ),
        "funding": (
            r"\b(?:funded by|funding|financial support|supported by)\b",
        ),
    }
    for key, patterns in fields.items():
        match = _first_matching_sentence(sentences, patterns)
        if match:
            card[key] = match

    card["key_findings"] = _key_result_sentences(sentences)
    card["extraction_note"] = (
        "Fields are machine-extracted clues, not verified evidence. Open the cited page before reuse."
    )
    return card


def card_to_json(card: dict[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))
