from __future__ import annotations

import csv
import io
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from math import sqrt
from pathlib import Path
from statistics import median
from typing import Any, Literal
from urllib.parse import quote

import httpx
import pypdfium2 as pdfium

from research_memory.config import Settings
from research_memory.utils import compact_whitespace, normalize_title

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
EXPLICIT_DOI_RE = re.compile(
    r"(?:\bdoi\s*[:=]\s*|https?://(?:dx\.)?doi\.org/)"
    r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    re.IGNORECASE,
)
PMID_RE = re.compile(r"\bPMID\s*[:#]?\s*(\d{6,9})\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


class PdfExtractionError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(slots=True)
class TextBlock:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    role: Literal["body", "header", "footer"] = "body"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, str | float]:
        return asdict(self)


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    width: float
    height: float
    text: str
    blocks: list[TextBlock]
    extraction_method: Literal["pdfium", "ocr", "empty"]
    confidence: float


@dataclass(slots=True)
class ExtractedPdf:
    pages: list[str]
    metadata: dict[str, str]
    page_count: int
    layout_pages: list[ExtractedPage]
    ocr_pages: int = 0

    @property
    def full_text(self) -> str:
        return "\n\n".join(self.pages)


@dataclass(slots=True)
class _PageLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(slots=True)
class _LayoutTitle:
    text: str
    lines: list[_PageLine]
    start_index: int
    end_index: int


def _normalize_repeated_line(text: str) -> str:
    normalized = compact_whitespace(text).lower()
    normalized = re.sub(r"\b\d+\b", "#", normalized)
    return normalized[:180]


def _order_band(blocks: list[TextBlock], width: float) -> list[TextBlock]:
    if len(blocks) < 4:
        return sorted(blocks, key=lambda block: (-block.y1, block.x0))
    left = [block for block in blocks if (block.x0 + block.x1) / 2 < width * 0.48]
    right = [block for block in blocks if (block.x0 + block.x1) / 2 > width * 0.52]
    left_narrow = [block for block in left if block.x1 <= width * 0.62]
    right_narrow = [block for block in right if block.x0 >= width * 0.38]
    two_columns = len(left_narrow) >= 2 and len(right_narrow) >= 2
    if not two_columns:
        return sorted(blocks, key=lambda block: (-block.y1, block.x0))
    middle = [block for block in blocks if block not in left and block not in right]
    return (
        sorted(left, key=lambda block: (-block.y1, block.x0))
        + sorted(middle, key=lambda block: (-block.y1, block.x0))
        + sorted(right, key=lambda block: (-block.y1, block.x0))
    )


def _reading_order(blocks: list[TextBlock], width: float) -> list[TextBlock]:
    """Apply a conservative XY-cut so two-column pages read down each column."""

    if not blocks:
        return []
    wide = [
        block for block in blocks if (block.x1 - block.x0) >= width * 0.66 and block.role == "body"
    ]
    if not wide:
        return _order_band(blocks, width)

    ordered: list[TextBlock] = []
    remaining = set(range(len(blocks)))
    separators = sorted(
        ((index, block) for index, block in enumerate(blocks) if block in wide),
        key=lambda item: -item[1].y1,
    )
    top = float("inf")
    for separator_index, separator in separators:
        band_indices = [
            index
            for index in remaining
            if index != separator_index
            and separator.y1 < blocks[index].y1 <= top
            and blocks[index].role == "body"
        ]
        ordered.extend(_order_band([blocks[index] for index in band_indices], width))
        remaining.difference_update(band_indices)
        if separator_index in remaining:
            ordered.append(separator)
            remaining.remove(separator_index)
        top = separator.y0
    ordered.extend(_order_band([blocks[index] for index in remaining], width))
    return ordered


def _native_blocks(page: pdfium.PdfPage) -> list[TextBlock]:
    text_page = page.get_textpage()
    try:
        blocks: list[TextBlock] = []
        seen: set[tuple[int, int, int, int, str]] = set()
        for index in range(text_page.count_rects()):
            left, bottom, right, top = text_page.get_rect(index)
            text = compact_whitespace(text_page.get_text_bounded(left, bottom, right, top))
            if not text:
                continue
            key = (
                round(left),
                round(bottom),
                round(right),
                round(top),
                text,
            )
            if key in seen:
                continue
            seen.add(key)
            blocks.append(
                TextBlock(
                    text=text,
                    x0=float(left),
                    y0=float(bottom),
                    x1=float(right),
                    y1=float(top),
                )
            )
        return blocks
    finally:
        text_page.close()


def _clip_blocks_to_page(
    blocks: list[TextBlock],
    width: float,
    height: float,
) -> list[TextBlock]:
    """Keep stored highlight geometry inside the visible PDF page bounds."""

    clipped: list[TextBlock] = []
    for block in blocks:
        block.x0 = max(0.0, min(float(width), block.x0))
        block.y0 = max(0.0, min(float(height), block.y0))
        block.x1 = max(0.0, min(float(width), block.x1))
        block.y1 = max(0.0, min(float(height), block.y1))
        if block.x1 > block.x0 and block.y1 > block.y0:
            clipped.append(block)
    return clipped


def _ocr_blocks(
    page: pdfium.PdfPage,
    *,
    tesseract_path: str,
    language: str,
    max_pixels: int,
    scale: float = 2.5,
) -> list[TextBlock]:
    width, height = page.get_size()
    requested_pixels = max(1.0, width * scale) * max(1.0, height * scale)
    if requested_pixels > max_pixels:
        scale *= sqrt(max_pixels / requested_pixels)
    image = page.render(scale=scale).to_pil()
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    command = [
        tesseract_path,
        "stdin",
        "stdout",
        "-l",
        language,
        "--psm",
        "3",
        "tsv",
    ]
    try:
        result = subprocess.run(
            command,
            input=payload.getvalue(),
            capture_output=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PdfExtractionError(
            "Local OCR could not be started.",
            code="ocr_unavailable",
            retryable=True,
        ) from exc
    if result.returncode != 0:
        raise PdfExtractionError(
            "Local OCR failed for this page.",
            code="ocr_failed",
            retryable=True,
        )

    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    reader = csv.DictReader(
        io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"
    )
    for row in reader:
        text = compact_whitespace(row.get("text", ""))
        try:
            confidence = float(row.get("conf", "-1"))
        except ValueError:
            confidence = -1
        if not text or confidence < 0:
            continue
        key = (
            row.get("block_num", ""),
            row.get("par_num", ""),
            row.get("line_num", ""),
        )
        grouped.setdefault(key, []).append(row)

    blocks: list[TextBlock] = []
    for words in grouped.values():
        text = compact_whitespace(" ".join(word.get("text", "") for word in words))
        if not text:
            continue
        x_values = [float(word["left"]) for word in words]
        y_values = [float(word["top"]) for word in words]
        right_values = [float(word["left"]) + float(word["width"]) for word in words]
        bottom_values = [float(word["top"]) + float(word["height"]) for word in words]
        confidences = [max(0.0, float(word.get("conf", "0"))) for word in words]
        blocks.append(
            TextBlock(
                text=text,
                x0=min(x_values) / scale,
                y0=height - max(bottom_values) / scale,
                x1=max(right_values) / scale,
                y1=height - min(y_values) / scale,
                confidence=sum(confidences) / (100 * len(confidences)),
            )
        )
    return blocks


def _tag_repeated_margins(pages: list[ExtractedPage]) -> None:
    if len(pages) < 3:
        return
    candidates: Counter[str] = Counter()
    for page in pages:
        seen_on_page: set[str] = set()
        for block in page.blocks:
            at_margin = block.y1 >= page.height * 0.95 or block.y0 <= page.height * 0.05
            normalized = _normalize_repeated_line(block.text)
            if at_margin and normalized and len(normalized) <= 180:
                seen_on_page.add(normalized)
        candidates.update(seen_on_page)
    threshold = max(3, round(len(pages) * 0.6))
    repeated = {text for text, count in candidates.items() if count >= threshold}
    if not repeated:
        return
    for page in pages:
        for block in page.blocks:
            normalized = _normalize_repeated_line(block.text)
            if normalized not in repeated:
                continue
            if block.y1 >= page.height * 0.95:
                block.role = "header"
            elif block.y0 <= page.height * 0.05:
                block.role = "footer"


def extract_pdf(
    path: Path,
    *,
    settings: Settings | None = None,
    password: str | None = None,
) -> ExtractedPdf:
    settings = settings or Settings()
    try:
        document = pdfium.PdfDocument(path, password=password)
    except Exception as exc:
        lowered = str(exc).lower()
        if "password" in lowered or "security" in lowered:
            raise PdfExtractionError(
                "The PDF is encrypted and requires a password for this session.",
                code="password_required",
                retryable=True,
            ) from exc
        raise PdfExtractionError(
            "The PDF is malformed or unsupported.",
            code="malformed_pdf",
            retryable=False,
        ) from exc

    try:
        page_count = len(document)
        if page_count < 1:
            raise PdfExtractionError(
                "The PDF contains no readable pages.",
                code="malformed_pdf",
                retryable=False,
            )
        if page_count > settings.max_pdf_pages:
            raise PdfExtractionError(
                f"The PDF has {page_count:,} pages; the configured limit is "
                f"{settings.max_pdf_pages:,}.",
                code="page_limit_exceeded",
                retryable=False,
            )
        raw_metadata = document.get_metadata_dict() or {}
        metadata = {
            str(key): compact_whitespace(str(value or "")) for key, value in raw_metadata.items()
        }
        layout_pages: list[ExtractedPage] = []
        ocr_pages = 0
        for page_index in range(page_count):
            page = document[page_index]
            try:
                width, height = page.get_size()
                blocks = _native_blocks(page)
                native_text_size = sum(len(block.text) for block in blocks)
                method: Literal["pdfium", "ocr", "empty"] = "pdfium"
                if native_text_size < 80 and settings.auto_ocr and settings.resolved_tesseract_path:
                    ocr = _ocr_blocks(
                        page,
                        tesseract_path=settings.resolved_tesseract_path,
                        language=settings.ocr_language,
                        max_pixels=settings.max_ocr_pixels,
                    )
                    if sum(len(block.text) for block in ocr) > native_text_size:
                        blocks = ocr
                        method = "ocr"
                        ocr_pages += 1
                blocks = _clip_blocks_to_page(blocks, float(width), float(height))
                if not blocks:
                    method = "empty"
                confidence = (
                    sum(block.confidence for block in blocks) / len(blocks) if blocks else 0.0
                )
                layout_pages.append(
                    ExtractedPage(
                        page_number=page_index + 1,
                        width=float(width),
                        height=float(height),
                        text="",
                        blocks=blocks,
                        extraction_method=method,
                        confidence=confidence,
                    )
                )
            finally:
                page.close()

        _tag_repeated_margins(layout_pages)
        for page in layout_pages:
            body_blocks = [block for block in page.blocks if block.role == "body"]
            ordered = _reading_order(body_blocks, page.width)
            page.blocks = ordered + [block for block in page.blocks if block.role != "body"]
            page.text = "\n".join(block.text for block in ordered)
        return ExtractedPdf(
            pages=[page.text for page in layout_pages],
            metadata=metadata,
            page_count=page_count,
            layout_pages=layout_pages,
            ocr_pages=ocr_pages,
        )
    finally:
        document.close()


def _clean_metadata_text(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\u0002", "")
    value = re.sub(r"[\u2020\u2021*]+$", "", value.strip())
    value = re.sub(r"\b(?:fl|fi|ff|Th)\s+(?=[a-z])", lambda match: match.group(0).strip(), value)
    value = re.sub(r"\s+([,;:.?!])", r"\1", value)
    value = re.sub(r"([(\[])\s+", r"\1", value)
    return compact_whitespace(value)


def _looks_like_title(value: str) -> bool:
    value = _clean_metadata_text(value)
    lowered = value.lower()
    bad_fragments = (
        "microsoft word",
        "untitled",
        "acrobat",
        "document1",
        "springerlink",
        "downloaded from",
        "conception and design",
        "administrative support",
        "provision of study materials",
        "collection and assembly of data",
        "manuscript writing",
        "all authors",
        "journal homepage",
        "contents lists available",
    )
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", value)
    if not (12 <= len(value) <= 500 and len(words) >= 2):
        return False
    if any(fragment in lowered for fragment in bad_fragments):
        return False
    if re.search(r"\.(?:indd|qxd|docx?|pdf|rtf|psd)$", lowered):
        return False
    if re.search(r"\(\s*grade\s+[a-d]\s*\)\s*$", value, re.IGNORECASE):
        return False
    if value.count(";") >= 3 or value.startswith((",", ":", ";")):
        return False
    return not (value[:1].islower() and len(words) > 5)


def _merge_inline_blocks(blocks: list[TextBlock]) -> str:
    max_height = max((block.y1 - block.y0 for block in blocks), default=0.0)
    filtered = [
        block
        for block in blocks
        if (block.y1 - block.y0) >= max_height * 0.65
        or re.fullmatch(
            r"(?:MD|DO|PhD|MSc|MPH|MBBS|MDCM|FCCP|RN|MS)[,;]?",
            block.text.strip(),
            re.IGNORECASE,
        )
        or (
            len(block.text.strip()) == 1
            and block.text.strip().isalpha()
            and not block.text.strip().isascii()
        )
    ]
    ordered = sorted(filtered, key=lambda block: block.x0)
    merged = ""
    right = 0.0
    for block in ordered:
        fragment = _clean_metadata_text(block.text)
        if not fragment:
            continue
        if not merged:
            merged = fragment
            right = block.x1
            continue
        previous_words = merged.split()
        fragment_words = fragment.split()
        for count in range(min(3, len(previous_words), len(fragment_words)), 0, -1):
            if [word.lower() for word in previous_words[-count:]] == [
                word.lower() for word in fragment_words[:count]
            ]:
                fragment_words = fragment_words[count:]
                fragment = " ".join(fragment_words)
                break
        if not fragment:
            right = max(right, block.x1)
            continue
        gap = block.x0 - right
        last_word = merged.split()[-1]
        first_word = fragment.split()[0]
        if gap <= 0 and len(last_word) >= 2 and first_word.lower().startswith(last_word.lower()):
            merged = merged[: -len(last_word)]
        separator = "" if gap <= 2.5 or merged.endswith(("-", "\u2010", "\u2011")) else " "
        merged = f"{merged}{separator}{fragment}"
        right = max(right, block.x1)
    return _clean_metadata_text(merged)


def _page_lines(page: ExtractedPage) -> list[_PageLine]:
    horizontal_blocks = [
        block
        for block in page.blocks
        if block.role == "body"
        and block.text.strip()
        and 1.5 <= (block.y1 - block.y0) <= min(45.0, page.height * 0.08)
        and not ((block.x1 - block.x0) < 12 and (block.y1 - block.y0) > 24)
    ]
    groups: list[list[TextBlock]] = []
    for block in sorted(
        horizontal_blocks,
        key=lambda item: (-(item.y0 + item.y1) / 2, item.x0),
    ):
        block_center = (block.y0 + block.y1) / 2
        best_group: list[TextBlock] | None = None
        best_distance = float("inf")
        for group in groups:
            group_y0 = min(item.y0 for item in group)
            group_y1 = max(item.y1 for item in group)
            group_center = (group_y0 + group_y1) / 2
            overlap = min(block.y1, group_y1) - max(block.y0, group_y0)
            minimum_height = min(block.y1 - block.y0, group_y1 - group_y0)
            distance = abs(block_center - group_center)
            if overlap >= minimum_height * 0.45 or distance <= max(2.5, minimum_height * 0.35):
                if distance < best_distance:
                    best_group = group
                    best_distance = distance
        if best_group is None:
            groups.append([block])
        else:
            best_group.append(block)

    lines = [
        _PageLine(
            text=_merge_inline_blocks(group),
            x0=min(block.x0 for block in group),
            y0=min(block.y0 for block in group),
            x1=max(block.x1 for block in group),
            y1=max(block.y1 for block in group),
        )
        for group in groups
    ]
    return sorted((line for line in lines if line.text), key=lambda line: (-line.y1, line.x0))


def _looks_like_author_line(value: str) -> bool:
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "abstract",
            "department",
            "university",
            "hospital",
            "correspondence",
            "contribution",
            "submitted",
            "received",
            "accepted",
            "published",
            "journal homepage",
            "doi",
            "http",
        )
    ):
        return False
    if not (2 <= len(value.split()) <= 100):
        return False
    credentials = re.search(
        r"\b(?:MD|DO|PhD|MSc|MPH|MBBS|MDCM|FCCP|RN|MS)\b",
        value,
        re.IGNORECASE,
    )
    full_names = re.findall(
        r"\b(?:[A-Z][a-z'-]+|[A-Z]\.?)(?:\s+(?:[A-Z][a-z'-]+|[A-Z]\.?)){1,3}\b",
        value,
    )
    initialed_name = re.fullmatch(
        r"(?:[A-Z][a-z'-]+\s+)?(?:[A-Z]\.\s+)+[A-Z][A-Za-z'-]+",
        value.strip(" ,;"),
    )
    bare_initial_name = re.search(
        r"(?:^|,\s*)(?:[A-Z]\s+){1,3}(?:[A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+)?)",
        value,
    )
    has_author_separator = any(separator in value for separator in (",", ";", " & "))
    return bool(
        credentials
        or initialed_name
        or (has_author_separator and (len(full_names) >= 2 or bare_initial_name))
    )


def _line_is_non_title(line: _PageLine) -> bool:
    lowered = line.text.lower().strip(" :")
    exact_labels = {
        "paper",
        "review article",
        "original article",
        "original research",
        "original investigation",
        "special features",
        "key words",
        "keywords",
        "abstract",
        "bts guidelines",
        "chest topics in practice management",
    }
    if lowered in exact_labels or _looks_like_author_line(line.text):
        return True
    if lowered.startswith("symposium"):
        return True
    return any(
        marker in lowered
        for marker in (
            "access this article",
            "contents lists available",
            "journal homepage",
            "downloaded from",
            "copyright",
            "submitted ",
            "received ",
            "accepted ",
            "published ",
            "doi:",
            "doi.org/",
            "http://",
            "https://",
            "issn:",
            "contributions:",
            "correspondence to",
        )
    )


def _layout_title_candidate(page: ExtractedPage) -> _LayoutTitle | None:
    lines = _page_lines(page)
    body_heights = [
        line.height
        for line in lines
        if 4 <= line.height <= 16 and 3 <= len(line.text.split()) <= 35
    ]
    typical_height = median(body_heights) if body_heights else 8.0
    scored: list[tuple[float, int]] = []
    for index, line in enumerate(lines):
        if (
            (line.y0 + line.y1) / 2 < page.height * 0.46
            or line.height < max(10.0, typical_height * 1.05)
            or _line_is_non_title(line)
            or not _looks_like_title(line.text)
        ):
            continue
        if index:
            previous = lines[index - 1]
            gap = previous.y0 - line.y1
            if (
                0 <= gap <= max(14.0, previous.height * 0.9)
                and previous.height >= line.height * 0.72
                and not _line_is_non_title(previous)
                and _looks_like_title(previous.text)
            ):
                continue
        word_count = len(line.text.split())
        score = (
            min(line.height / max(typical_height, 1.0), 4.0) * 4
            + ((line.y0 + line.y1) / 2 / page.height) * 12
            + min(word_count, 12) * 0.12
        )
        scored.append((score, index))
    if not scored:
        return None

    _, start_index = max(scored)
    selected = [lines[start_index]]
    end_index = start_index
    start_height = lines[start_index].height
    for index in range(start_index + 1, min(len(lines), start_index + 5)):
        line = lines[index]
        previous = selected[-1]
        gap = previous.y0 - line.y1
        if gap < -2:
            continue
        if (
            gap > max(15.0, start_height * 0.9)
            or line.height < max(9.5, typical_height * 0.9, start_height * 0.5)
            or _line_is_non_title(line)
            or (
                not _looks_like_title(line.text)
                and line.text.lower().strip(" :") not in {"review", "a review", "perspective"}
            )
        ):
            break
        selected.append(line)
        end_index = index

    title = _clean_metadata_text(" ".join(line.text for line in selected)).strip(" *")
    short_fragments = [
        token
        for token in re.findall(r"[A-Za-z]+", title)
        if len(token) <= 2 and token.lower() not in {"a", "an", "of", "in", "to", "on"}
    ]
    if not _looks_like_title(title) or len(short_fragments) >= 4:
        return None
    return _LayoutTitle(title, lines, start_index, end_index)


def _filename_title(file_path: Path) -> str:
    value = re.sub(r"\.\d{1,3}$", "", file_path.stem)
    value = compact_whitespace(re.sub(r"_+", " ", value)).strip(" ._-")
    lowered = value.lower()
    if lowered in {"article", "document", "download", "full text", "paper", "untitled"}:
        return ""
    if not re.search(r"[A-Za-z]", value):
        return ""
    return value if _looks_like_title(value) else ""


def _title_similarity(left: str, right: str) -> tuple[float, float]:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    return sequence, overlap


def _choose_title(extracted: ExtractedPdf, file_path: Path) -> tuple[str, _LayoutTitle | None]:
    metadata_title = _clean_metadata_text(
        extracted.metadata.get("Title", "") or extracted.metadata.get("title", "")
    )
    if not _looks_like_title(metadata_title):
        metadata_title = ""
    filename_title = _filename_title(file_path)
    layout = _layout_title_candidate(extracted.layout_pages[0]) if extracted.layout_pages else None
    layout_title = layout.text if layout else ""

    if layout_title and metadata_title:
        layout_normalized = normalize_title(layout_title)
        metadata_normalized = normalize_title(metadata_title)
        if layout_normalized == metadata_normalized:
            return metadata_title, layout
        sequence, overlap = _title_similarity(layout_title, metadata_title)
        if (
            metadata_normalized in layout_normalized
            and len(layout_title.split()) <= len(metadata_title.split()) + 12
        ):
            if layout_title.lower().startswith(
                metadata_title.lower()
            ) and not metadata_title.endswith((".", ":", "?", "!")):
                remainder = layout_title[len(metadata_title) :].strip(" :-")
                if remainder:
                    return f"{metadata_title}: {remainder}", layout
            return layout_title, layout
        if layout_normalized in metadata_normalized:
            return metadata_title, layout
        if sequence >= 0.78 or overlap >= 0.8:
            return (
                layout_title
                if len(layout_title.split()) > len(metadata_title.split())
                else metadata_title,
                layout,
            )
        if filename_title:
            layout_support = max(_title_similarity(layout_title, filename_title))
            metadata_support = max(_title_similarity(metadata_title, filename_title))
            if layout_support > metadata_support + 0.12:
                return layout_title, layout
        return metadata_title, layout

    if layout_title and filename_title:
        assert layout is not None
        sequence, overlap = _title_similarity(layout_title, filename_title)
        if sequence >= 0.55 or overlap >= 0.65:
            selected_lines = layout.lines[layout.start_index : layout.end_index + 1]
            title_prefix = ""
            for line in selected_lines[:-1]:
                title_prefix = _clean_metadata_text(f"{title_prefix} {line.text}")
                if normalize_title(title_prefix) != normalize_title(filename_title):
                    continue
                remainder = layout_title[len(title_prefix) :].strip(" :-")
                if remainder and not filename_title.endswith((".", ":", "?", "!")):
                    return f"{title_prefix}: {remainder}", layout
            return layout_title, layout
        return filename_title, layout
    if layout_title:
        return layout_title, layout
    if metadata_title:
        return metadata_title, layout
    if filename_title:
        return filename_title, layout
    fallback = compact_whitespace(file_path.stem.replace("_", " ").replace("-", " "))
    return fallback, layout


def _extract_abstract(pages: list[str]) -> str:
    head = "\n".join(pages[:4])
    match = re.search(
        r"(?m)^[ \t]*(?:"
        r"ABSTRACT[ \t]*:?[ \t]*|"
        r"Abstract[ \t]*(?:(?:[:—-])[ \t]*|(?=\n|[A-Z]))"
        r")",
        head,
    )
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


def _infer_authors_from_text(first_page: str, title: str) -> str:
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


def _clean_authors(value: str) -> str:
    value = re.sub(r"[\u2020\u2021*]+", "", value)
    value = re.sub(
        r",\s*[a-z]\s+(?=(?:MD|DO|PhD|MSc|MPH|MBBS|MDCM|FCCP|RN|MS)\b)",
        ", ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(MD|DO|PhD|MSc|MPH|MBBS|MDCM|FCCP|RN|MS)[a-z]\b",
        r"\1",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<=[A-Za-z])\d{1,2}\b", "", value)
    value = re.sub(r"(?<=[a-z])\s+[a-z]\s*,", ",", value)
    value = re.sub(
        r"(?<=[,;])\s*[a-z]\s*(?=[,;])",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r",\s*([a-z])\1\s*,\s*(?=MD\b)", ", ", value)
    value = re.sub(r"\s*;\s*[,;]+\s*", "; ", value)
    value = re.sub(r"\s*,\s*;\s*", "; ", value)
    value = re.sub(r",\s*,+", ", ", value)
    value = re.sub(r"\b(?:MD|DO)\s+[a-z]\b", lambda match: match.group(0)[:2], value)
    value = re.sub(r"\s+([,;])", r"\1", value)
    value = re.sub(r"([,;])(?=\S)", r"\1 ", value)
    return compact_whitespace(value).strip(" ,;")


def _infer_authors_from_layout(layout: _LayoutTitle | None) -> str:
    if not layout:
        return ""
    selected: list[str] = []
    title_bottom = layout.lines[-1].y0
    for line in layout.lines[layout.end_index + 1 : layout.end_index + 12]:
        if title_bottom - line.y1 > 125:
            break
        if re.fullmatch(r"[\d\s,*\u2020\u2021]+", line.text) or re.fullmatch(
            r"[a-z](?:[\s,;*\d\u2020\u2021]*)",
            line.text,
        ):
            continue
        lowered = line.text.lower()
        if any(
            marker in lowered
            for marker in (
                "abstract",
                "background:",
                "materials and methods:",
                "methods:",
                "department",
                "division of ",
                "university",
                "hospital",
                "correspondence",
                "contribution",
                "submitted",
                "received",
                "accepted",
                "published",
                "keywords",
                "key words",
                "purpose of review",
                "to cite this article",
            )
        ):
            break
        if _looks_like_author_line(line.text):
            selected.append(line.text)
            continue
        if selected and (lowered.startswith(("and ", "on behalf of ")) or " & " in line.text):
            selected.append(line.text)
            continue
        if selected:
            break
    return _clean_authors(", ".join(selected))[:2000]


def _choose_authors(extracted: ExtractedPdf, title: str, layout: _LayoutTitle | None) -> str:
    embedded = _clean_authors(
        extracted.metadata.get("Author", "") or extracted.metadata.get("author", "")
    )
    if not re.search(r"[A-Za-z]", embedded):
        embedded = ""
    inferred = _infer_authors_from_layout(layout)
    if not inferred:
        inferred = _clean_authors(
            _infer_authors_from_text(extracted.pages[0] if extracted.pages else "", title)
        )
    if not embedded:
        return inferred
    if not inferred:
        return embedded
    suspicious = (
        "to cite this article" in inferred.lower()
        or "background:" in inferred.lower()
        or len(re.findall(r"(?:^|[,;]\s*)[A-Za-z]\s*(?=[,;]|$)", inferred)) >= 2
    )
    inferred_author_count = (
        inferred.count(";") + inferred.lower().count(" and ") + inferred.count(" & ") + 1
    )
    # Multicenter biomedical papers commonly have dozens of legitimate authors.
    # The title-relative geometry and stop markers above are a safer boundary than
    # rejecting a valid byline merely because it contains more than 12 names.
    if suspicious or inferred_author_count > 60:
        return embedded
    embedded_tokens = {
        token
        for token in normalize_title(embedded).split()
        if len(token) > 2 and token.lower() not in {"md", "mph", "fccp", "phd"}
    }
    inferred_tokens = set(normalize_title(inferred).split())
    if embedded_tokens & inferred_tokens and len(inferred_tokens) > len(embedded_tokens) + 1:
        return inferred
    return embedded


def _metadata_date_year(value: str, current_year: int) -> int | None:
    match = re.search(r"(?:D:)?((?:19|20)\d{2})", value)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1900 <= year <= current_year else None


def _infer_publication_year(extracted: ExtractedPdf) -> int | None:
    current_year = datetime.now(UTC).year + 1
    candidates: list[tuple[int, int, int]] = []
    position = 0

    def add_matches(corpus: str, pattern: str, score: int) -> None:
        nonlocal position
        for match in re.finditer(pattern, corpus, re.IGNORECASE):
            year = int(match.group("year"))
            if 1900 <= year <= current_year:
                candidates.append((score, -position, year))
                position += 1

    subject = extracted.metadata.get("Subject", "") or extracted.metadata.get("subject", "")
    add_matches(subject, r"\b(?P<year>(?:19|20)\d{2})\b", 120)

    layout_head = "\n".join(
        line.text for page in extracted.layout_pages[:2] for line in _page_lines(page)
    )
    page_head = "\n".join(extracted.pages[:2])
    head = f"{page_head}\n{layout_head}"[:80_000]
    strong_patterns = (
        r"\b(?P<year>(?:19|20)\d{2})\s*;\s*\d{1,4}(?:\s*\(\d+\))?\s*[:;]",
        r"\(\s*(?P<year>(?:19|20)\d{2})\s*\)\s*\d+\s*[-\u2013\u2014]",
        r"\b(?:CHEST|Clin(?:ics)?\s+Chest\s+Med|ERJ\s+Open\s+Res)"
        r"\s+(?P<year>(?:19|20)\d{2})\s*[;,:]",
        r"\bJ(?:ournal)?\s+[A-Za-z][A-Za-z .&-]{2,70}\s+"
        r"(?P<year>(?:19|20)\d{2})\s*[;,:]",
        r"\b(?:Volume|Vol\.?)\s+\d+[^.\n]{0,50}\b(?P<year>(?:19|20)\d{2})\b",
    )
    for pattern in strong_patterns:
        add_matches(head, pattern, 110)
    add_matches(
        head,
        r"\b(?:published(?:\s+online)?|first\s+published)[^.\n]{0,80}"
        r"\b(?P<year>(?:19|20)\d{2})\b",
        95,
    )
    add_matches(
        head,
        r"(?:copyright|\u00a9)\s*(?P<year>(?:19|20)\d{2})\b",
        80,
    )

    creation_year = _metadata_date_year(
        extracted.metadata.get("CreationDate", "") or extracted.metadata.get("creationdate", ""),
        current_year,
    )
    if creation_year:
        candidates.append((70, -position, creation_year))
        position += 1
    modification_year = _metadata_date_year(
        extracted.metadata.get("ModDate", "") or extracted.metadata.get("moddate", ""),
        current_year,
    )
    if modification_year:
        candidates.append((45, -position, modification_year))

    if not candidates:
        return None
    return max(candidates)[2]


def _infer_journal(extracted: ExtractedPdf) -> str:
    subject = _clean_metadata_text(
        extracted.metadata.get("Subject", "") or extracted.metadata.get("subject", "")
    ).strip(" .")
    if subject:
        citation = re.match(r"^(?P<journal>.+?),\s*\d+\s*(?:\(|,|\d)", subject)
        if citation:
            return citation.group("journal").strip()[:500]
        if "doi" not in subject.lower() and len(subject) <= 150:
            return subject[:500]

    layout_head = "\n".join(
        line.text for page in extracted.layout_pages[:2] for line in _page_lines(page)
    )
    page_head = "\n".join(extracted.pages[:2])
    head = f"{page_head}\n{layout_head}"[:80_000]
    citation_patterns = (
        r"\b(?P<journal>Clin(?:ics)?\s+Chest\s+Med)\s+\d+\s*\(\d{4}\)",
        r"\b(?P<journal>CHEST)\s+\d{4}\s*;",
        r"\b(?P<journal>ERJ\s+Open\s+Res)\s+\d{4}\s*;",
        r"\b(?P<journal>J\s+Natl\s+Compr\s+Canc\s+Netw)\s+\d{4}\s*;",
        r"\b(?P<journal>Thorax)\s+\d{4}\s*;",
        r"\b(?P<journal>Current\s+Opinion\s+in\s+Anaesthesiology)\s+\d{4}\b",
        r"\b(?P<journal>Journal\s+of\s+Thoracic\s+Disease),\s+Vol\b",
        r"\b(?P<journal>European\s+Clinical\s+Respiratory\s+Journal)\b",
        r"\b(?P<journal>International\s+Journal\s+of\s+Critical\s+Illness"
        r"\s+and\s+Injury\s+Science)\b",
    )
    for pattern in citation_patterns:
        match = re.search(pattern, head, re.IGNORECASE)
        if match:
            return compact_whitespace(match.group("journal"))[:500]
    return ""


def _infer_source_type(title: str, abstract: str) -> str:
    """Use only title/abstract so cited studies cannot classify the article."""

    corpus = f"{title}\n{abstract}".lower()
    if (
        "practice guideline" in corpus
        or "clinical guideline" in corpus
        or "consensus statement" in corpus
    ):
        return "guideline"
    if "systematic review" in corpus or "meta-analysis" in corpus or "meta analysis" in corpus:
        return "systematic_review"
    if "randomized controlled trial" in corpus or "randomised controlled trial" in corpus:
        return "randomized_trial"
    if "prospective cohort" in corpus:
        return "prospective_cohort"
    if "retrospective" in title.lower():
        return "retrospective_study"
    if "case report" in title.lower():
        return "case_report"
    if "review" in title.lower():
        return "review"
    return "journal_article"


def _extract_doi(first_page: str, metadata: dict[str, str]) -> str:
    for key, value in metadata.items():
        if "doi" not in key.lower():
            continue
        match = DOI_RE.search(value)
        if match:
            return match.group(0).rstrip(".,;)]}").lower()
    metadata_text = "\n".join(metadata.values())
    for corpus in (metadata_text, first_page[:6_000]):
        explicit = EXPLICIT_DOI_RE.search(corpus)
        if explicit:
            return explicit.group(1).rstrip(".,;)]}").lower()
    # Unlabelled DOI-like strings can be citations, so they never drive an auto-merge.
    return ""


def _suspects_multiple_articles(extracted: ExtractedPdf) -> bool:
    """Conservatively flag bundles with a second abstract and distinct identifier."""

    if len(extracted.pages) < 2:
        return False
    first_head = extracted.pages[0][:6_000]
    first_doi = _extract_doi(first_head, extracted.metadata)
    first_pmid_match = PMID_RE.search(first_head)
    first_pmid = first_pmid_match.group(1) if first_pmid_match else ""
    for page in extracted.pages[1:]:
        head = page[:6_000]
        if not re.search(r"(?im)^\s*abstract\s*[:—-]?\s*$", head):
            continue
        doi = _extract_doi(head, {})
        pmid_match = PMID_RE.search(head)
        pmid = pmid_match.group(1) if pmid_match else ""
        if (doi and doi != first_doi) or (pmid and pmid != first_pmid):
            return True
    return False


def infer_metadata(extracted: ExtractedPdf, file_path: Path) -> dict[str, Any]:
    first_page = extracted.pages[0] if extracted.pages else ""
    title, title_layout = _choose_title(extracted, file_path)
    fallback_title = _filename_title(file_path) or file_path.stem

    doi = _extract_doi(first_page, extracted.metadata)
    pmid_match = PMID_RE.search(first_page[:6_000])
    pmid = pmid_match.group(1) if pmid_match else ""

    publication_year = _infer_publication_year(extracted)
    authors = _choose_authors(extracted, title, title_layout)

    abstract = _extract_abstract(extracted.pages)
    journal = _infer_journal(extracted)
    source_type = _infer_source_type(title, abstract)

    return {
        "title": title[:1000] or fallback_title,
        "normalized_title": normalize_title(title or fallback_title),
        "authors": authors[:2000],
        "journal": journal,
        "publication_year": publication_year,
        "doi": doi,
        "pmid": pmid,
        "abstract": abstract,
        "page_count": extracted.page_count,
        "source_type": source_type,
        "metadata_status": "local",
        "multi_article_suspected": _suspects_multiple_articles(extracted),
    }


async def enrich_from_crossref(
    metadata: dict[str, Any], *, mailto: str | None = None, timeout: float = 12.0
) -> dict[str, Any]:
    """Enrich by identifier only, after the user has enabled network metadata."""

    doi = metadata.get("doi")
    if not doi:
        return metadata
    headers = {"User-Agent": "ResearchMemory/0.2" + (f" (mailto:{mailto})" if mailto else "")}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers=headers, follow_redirects=False
        ) as client:
            response = await client.get(
                f"https://api.crossref.org/works/{quote(str(doi), safe='')}"
            )
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


async def enrich_from_pubmed(
    metadata: dict[str, Any], *, email: str | None = None, timeout: float = 12.0
) -> dict[str, Any]:
    """Enrich by PMID only through NCBI ESummary after explicit consent."""

    pmid = str(metadata.get("pmid") or "").strip()
    if not pmid:
        return metadata
    parameters = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "json",
        "tool": "ResearchMemory",
    }
    if email:
        parameters["email"] = email
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params=parameters,
            )
            response.raise_for_status()
            record = (response.json().get("result") or {}).get(pmid, {})
    except Exception:
        return metadata
    if not isinstance(record, dict) or not record:
        return metadata

    enriched = dict(metadata)
    title = compact_whitespace(str(record.get("title") or ""))
    if title:
        enriched["title"] = title[:1000]
        enriched["normalized_title"] = normalize_title(enriched["title"])
    authors = [
        compact_whitespace(str(author.get("name") or ""))
        for author in record.get("authors") or []
        if isinstance(author, dict)
    ]
    authors = [author for author in authors if author]
    if authors:
        enriched["authors"] = ", ".join(authors)[:2000]
    journal = compact_whitespace(str(record.get("fulljournalname") or record.get("source") or ""))
    if journal:
        enriched["journal"] = journal[:500]
    publication = str(record.get("pubdate") or "")
    year = YEAR_RE.search(publication)
    if year:
        enriched["publication_year"] = int(year.group(1))
    enriched["metadata_status"] = (
        "crossref+pubmed" if enriched.get("metadata_status") == "crossref" else "pubmed"
    )
    return enriched
