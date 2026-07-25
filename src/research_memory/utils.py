from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]{1,}")


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def slugify(value: str) -> str:
    normalized = normalize_title(value).replace(" ", "-")
    return normalized[:80] or "untitled"


def safe_filename(value: str) -> str:
    value = Path(value).name
    value = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", value).strip(" .")
    return value[:180] or "document.pdf"


def query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for token in WORD_RE.findall(query.lower()):
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def build_fts_query(query: str) -> str:
    """Create a safe, forgiving FTS query from natural-language input."""

    terms = query_terms(query)
    if not terms:
        return '""'
    escaped = [term.replace('"', '""') for term in terms[:24]]
    if len(escaped) == 1:
        return f'"{escaped[0]}"*'
    return " OR ".join(f'"{term}"*' for term in escaped)


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def truncate(value: str, limit: int = 220) -> str:
    value = compact_whitespace(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
