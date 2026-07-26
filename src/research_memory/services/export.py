from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


def _value(row: Mapping[str, Any], key: str, default: Any = "") -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def citation_key(row: Mapping[str, Any]) -> str:
    authors = str(_value(row, "authors", "") or "")
    family = re.split(r"[,;\s]", authors.strip())[0] if authors.strip() else "unknown"
    family = re.sub(r"[^A-Za-z0-9]", "", family).lower() or "unknown"
    year = _value(row, "publication_year", None) or "nd"
    title_words = re.findall(r"[A-Za-z0-9]+", str(_value(row, "title", "")))
    title_token = title_words[0].lower() if title_words else "article"
    return f"{family}{year}{title_token}"


def _bibtex_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("&", r"\&")
        .replace("%", r"\%")
    )


def document_to_bibtex(row: Mapping[str, Any]) -> str:
    fields = [
        ("title", _value(row, "title")),
        ("author", _value(row, "authors")),
        ("journal", _value(row, "journal")),
        ("year", _value(row, "publication_year")),
        ("doi", _value(row, "doi")),
    ]
    body = ",\n".join(f"  {name} = {{{_bibtex_escape(value)}}}" for name, value in fields if value)
    return f"@article{{{citation_key(row)},\n{body}\n}}"


def documents_to_bibtex(rows: Iterable[Mapping[str, Any]]) -> str:
    return "\n\n".join(document_to_bibtex(row) for row in rows) + "\n"


def document_to_ris(row: Mapping[str, Any]) -> str:
    lines = ["TY  - JOUR"]
    authors = str(_value(row, "authors", "") or "")
    for author in re.split(r"\s*;\s*|\s+and\s+", authors):
        if author.strip():
            lines.append(f"AU  - {author.strip()}")
    lines.append(f"TI  - {_value(row, 'title')}")
    if _value(row, "journal"):
        lines.append(f"JO  - {_value(row, 'journal')}")
    if _value(row, "publication_year"):
        lines.append(f"PY  - {_value(row, 'publication_year')}")
    if _value(row, "doi"):
        lines.append(f"DO  - {_value(row, 'doi')}")
    if _value(row, "pmid"):
        lines.append(f"AN  - PMID:{_value(row, 'pmid')}")
    if _value(row, "abstract"):
        lines.append(f"AB  - {_value(row, 'abstract')}")
    lines.append("ER  - ")
    return "\n".join(lines)


def documents_to_ris(rows: Iterable[Mapping[str, Any]]) -> str:
    return "\n\n".join(document_to_ris(row) for row in rows) + "\n"


def project_to_markdown(project: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> str:
    output = [
        f"# {_value(project, 'name')}",
        "",
        f"- **Type:** {str(_value(project, 'project_type')).replace('_', ' ')}",
    ]
    if _value(project, "central_question"):
        output.append(f"- **Central question:** {_value(project, 'central_question')}")
    if _value(project, "description"):
        output.extend(["", str(_value(project, "description"))])
    output.extend(["", "## Evidence table", ""])
    output.append("| Paper | Year | Type | Project status | Why saved | DOI |")
    output.append("|---|---:|---|---|---|---|")
    detail_sections: list[str] = []
    for row in rows:
        title = str(_value(row, "title")).replace("|", "\\|")
        why_saved = str(_value(row, "why_saved")).replace("|", "\\|")
        output.append(
            f"| {title} | {_value(row, 'publication_year', '') or ''} | "
            f"{str(_value(row, 'source_type')).replace('_', ' ')} | "
            f"{str(_value(row, 'project_status')).replace('_', ' ')} | {why_saved} | "
            f"{_value(row, 'doi')} |"
        )
        detail_sections.extend(
            [
                "",
                f"### {title}",
                "",
                f"- **Authors:** {_value(row, 'authors')}",
                f"- **Citation:** {_value(row, 'journal')} {_value(row, 'publication_year', '') or ''}",
                f"- **Project status:** {str(_value(row, 'project_status')).replace('_', ' ')}",
            ]
        )
        if _value(row, "why_saved"):
            detail_sections.append(f"- **Why saved:** {_value(row, 'why_saved')}")
        if _value(row, "user_summary"):
            detail_sections.extend(["", str(_value(row, "user_summary"))])
    output.extend(["", "## Paper notes"])
    output.extend(detail_sections)
    output.append("")
    return "\n".join(output)
