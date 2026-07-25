from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import httpx

from research_memory.utils import compact_whitespace, normalize_title


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
PMID_RE = re.compile(r"\bPMID\s*[:#]?\s*(\d{6,9})\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


@dataclass(slots=True)
class ExtractedPdf:
    pages: list[str]
    metadata: dict[str, str]
    page_count: int

    @property
    def full_text(self) -> str:
        return "\n\n".join(self.pages)


class PdfExtractionError(RuntimeError):
    pass


def extract_pdf(path: Path) -> ExtractedPdf:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise PdfExtractionError(f"Unable to open PDF: {exc}") from exc

    try:
        if document.needs_pass:
            raise PdfExtractionError("The PDF is encrypted and requires a password.")
        pages = [page.get_text("text", sort=True) or "" for page in document]
        raw_metadata = document.metadata or {}
        metadata = {str(k): compact_whitespace(str(v or "")) for k, v in raw_metadata.items()}
        return ExtractedPdf(pages=pages, metadata=metadata, page_count=document.page_count)
    finally:
        document.close()


def _looks_like_title(value: str) -> bool:
    lowered = value.lower()
    bad_fragments = (
        "microsoft word",
        "untitled",
        "acrobat",
        "document1",
        "springerlink",
        "downloaded from",
    )
    return 12 <= len(value) <= 500 and not any(fragment in lowered for fragment in bad_fragments)


def _title_from_first_page(first_page: str, fallback: str) -> str:
    lines = [compact_whitespace(line) for line in first_page.splitlines()]
    lines = [line for line in lines if line and 15 <= len(line) <= 260]
    candidates: list[str] = []
    for line in lines[:25]:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "doi:",
                "http://",
                "https://",
                "copyright",
                "abstract",
                "keywords",
                "received",
                "accepted",
                "published",
            )
        ):
            continue
        if len(line.split()) < 3:
            continue
        candidates.append(line)
    if not candidates:
        return fallback
    # Article titles tend to be among the longest early lines, but cap the bias
    # so an abstract sentence is not preferred over a real title.
    early = candidates[:10]
    early.sort(key=lambda item: (min(len(item), 180), -candidates.index(item)), reverse=True)
    return early[0]


def _extract_abstract(pages: list[str]) -> str:
    head = "\n".join(pages[:4])
    match = re.search(r"\babstract\b\s*[:—-]?\s*", head, re.IGNORECASE)
    if not match:
        return ""
    tail = head[match.end() :]
    stop = re.search(
        r"\n\s*(?:keywords?|introduction|background|methods?|materials and methods)\b",
        tail,
        re.IGNORECASE,
    )
    abstract = tail[: stop.start()] if stop else tail[:4000]
    return compact_whitespace(abstract)[:5000]


def _infer_authors(first_page: str, title: str) -> str:
    lines = [compact_whitespace(line) for line in first_page.splitlines() if line.strip()]
    title_norm = normalize_title(title)
    title_index = 0
    for index, line in enumerate(lines[:30]):
        if normalize_title(line) == title_norm or title_norm.startswith(normalize_title(line)):
            title_index = index
            break
    for line in lines[title_index + 1 : title_index + 7]:
        lowered = line.lower()
        if len(line) > 350 or any(
            marker in lowered
            for marker in ("abstract", "department", "university", "hospital", "doi", "http")
        ):
            continue
        if re.search(r"[A-Za-z].*(?:,| and |\b[A-Z]\.)", line) and not re.search(r"\d{4}", line):
            return line[:1000]
    return ""


def _infer_source_type(title: str, abstract: str, text: str) -> str:
    corpus = f"{title}\n{abstract}\n{text[:12000]}".lower()
    if "practice guideline" in corpus or "clinical guideline" in corpus or "consensus statement" in corpus:
        return "guideline"
    if "systematic review" in corpus or "meta-analysis" in corpus or "meta analysis" in corpus:
        return "systematic_review"
    if "randomized controlled trial" in corpus or "randomised controlled trial" in corpus:
        return "randomized_trial"
    if "prospective cohort" in corpus:
        return "prospective_cohort"
    if "retrospective" in corpus:
        return "retrospective_study"
    if "case report" in corpus:
        return "case_report"
    if "review" in title.lower():
        return "review"
    return "journal_article"


def infer_metadata(extracted: ExtractedPdf, file_path: Path) -> dict[str, Any]:
    full_text = extracted.full_text
    first_page = extracted.pages[0] if extracted.pages else ""
    metadata_title = compact_whitespace(extracted.metadata.get("title", ""))
    fallback_title = file_path.stem.replace("_", " ").replace("-", " ").strip()
    title = metadata_title if _looks_like_title(metadata_title) else _title_from_first_page(
        first_page, fallback_title
    )

    doi_match = DOI_RE.search(full_text[:100_000])
    doi = doi_match.group(0).rstrip(".,;)]}") if doi_match else ""
    pmid_match = PMID_RE.search(full_text[:100_000])
    pmid = pmid_match.group(1) if pmid_match else ""

    current_year = datetime.now().year + 1
    years = [int(value) for value in YEAR_RE.findall(full_text[:30_000])]
    plausible_years = [year for year in years if 1900 <= year <= current_year]
    publication_year = plausible_years[0] if plausible_years else None

    authors = compact_whitespace(extracted.metadata.get("author", ""))
    if not authors:
        authors = _infer_authors(first_page, title)

    abstract = _extract_abstract(extracted.pages)
    journal = compact_whitespace(extracted.metadata.get("subject", ""))[:500]
    source_type = _infer_source_type(title, abstract, full_text)

    return {
        "title": title[:1000] or fallback_title,
        "normalized_title": normalize_title(title or fallback_title),
        "authors": authors[:2000],
        "journal": journal,
        "publication_year": publication_year,
        "doi": doi.lower(),
        "pmid": pmid,
        "abstract": abstract,
        "page_count": extracted.page_count,
        "source_type": source_type,
        "metadata_status": "local",
    }


async def enrich_from_crossref(
    metadata: dict[str, Any], *, mailto: str | None = None, timeout: float = 12.0
) -> dict[str, Any]:
    """Enrich DOI metadata without making ingestion dependent on the network."""

    doi = metadata.get("doi")
    if not doi:
        return metadata
    headers = {"User-Agent": "ResearchMemory/0.1" + (f" (mailto:{mailto})" if mailto else "")}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            response = await client.get(f"https://api.crossref.org/works/{doi}")
            response.raise_for_status()
            message = response.json().get("message", {})
    except Exception:
        return metadata

    enriched = dict(metadata)
    titles = message.get("title") or []
    if titles:
        enriched["title"] = compact_whitespace(titles[0])[:1000]
        enriched["normalized_title"] = normalize_title(enriched["title"])
    authors = []
    for author in message.get("author") or []:
        full_name = compact_whitespace(f"{author.get('given', '')} {author.get('family', '')}")
        if full_name:
            authors.append(full_name)
    if authors:
        enriched["authors"] = ", ".join(authors)[:2000]
    containers = message.get("container-title") or []
    if containers:
        enriched["journal"] = compact_whitespace(containers[0])[:500]
    date_parts = ((message.get("published") or {}).get("date-parts") or [[]])[0]
    if date_parts and isinstance(date_parts[0], int):
        enriched["publication_year"] = date_parts[0]
    enriched["metadata_status"] = "crossref"
    return enriched
