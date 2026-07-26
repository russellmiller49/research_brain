from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight, Text
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

from research_memory.contracts import Annotation, AnnotationCreate
from research_memory.db import Database


class AnnotationService:
    def __init__(self, db: Database):
        self.db = db

    def list_for_document(
        self,
        document_id: int,
        *,
        file_id: int | None = None,
    ) -> list[Annotation]:
        where = "document_id = ? AND deleted_at IS NULL"
        parameters: list[object] = [document_id]
        if file_id is not None:
            where += " AND file_id = ?"
            parameters.append(file_id)
        rows = self.db.fetch_all(
            f"""
            SELECT * FROM annotations
            WHERE {where}
            ORDER BY page_number, created_at
            """,
            parameters,
        )
        return [self._contract(row) for row in rows]

    def create(self, document_id: int, value: AnnotationCreate) -> Annotation:
        file_row = self.db.fetch_one(
            """
            SELECT id FROM document_files
            WHERE id = ? AND document_id = ? AND availability = 'available'
            """,
            (value.asset_id, document_id),
        )
        if not file_row:
            raise ValueError("The selected asset is unavailable or does not belong to this article")
        document_row = self.db.fetch_one(
            "SELECT page_count FROM documents WHERE id = ? AND deleted_at IS NULL",
            (document_id,),
        )
        if not document_row:
            raise ValueError("The article is unavailable")
        page_count = int(document_row["page_count"] or 0)
        if value.page_number > page_count:
            raise ValueError("The annotation page is outside the indexed PDF")
        points = value.quad_points
        if value.annotation_type == "highlight" and (len(points) < 8 or len(points) % 8 != 0):
            raise ValueError("A highlight requires complete PDF quad points")
        if points and len(points) % 2 != 0:
            raise ValueError("Annotation coordinates must contain x/y pairs")
        if any(not math.isfinite(point) or point < 0 or point > 200_000 for point in points):
            raise ValueError("Annotation coordinates are invalid")
        if value.annotation_type == "highlight" and not value.selected_text.strip():
            raise ValueError("A text highlight requires selected text")
        annotation_id = str(uuid.uuid4())
        context_hash = (
            value.context_hash or hashlib.sha256(value.selected_text.encode("utf-8")).hexdigest()
        )
        self.db.execute(
            """
            INSERT INTO annotations(
                id, document_id, file_id, page_number, annotation_type, color,
                quad_points_json, selected_text, context_hash, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                document_id,
                value.asset_id,
                value.page_number,
                value.annotation_type,
                value.color,
                json.dumps(value.quad_points),
                value.selected_text,
                context_hash,
                value.comment,
            ),
        )
        row = self.db.fetch_one("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
        assert row is not None
        return self._contract(row)

    def delete(self, document_id: int, annotation_id: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE annotations
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND document_id = ? AND deleted_at IS NULL
            """,
            (annotation_id, document_id),
        )
        return cursor.rowcount == 1

    def export_markdown(
        self,
        document_id: int,
        title: str,
        *,
        file_id: int | None = None,
    ) -> str:
        output = [f"# Annotations: {title}", ""]
        for annotation in self.list_for_document(document_id, file_id=file_id):
            output.append(
                f"## Page {annotation.page_number} · {annotation.annotation_type.title()}"
            )
            output.append("")
            if annotation.selected_text:
                output.extend([f"> {annotation.selected_text}", ""])
            if annotation.comment:
                output.extend([annotation.comment, ""])
        return "\n".join(output).rstrip() + "\n"

    def export_xfdf(
        self,
        document_id: int,
        original_name: str,
        *,
        file_id: int | None = None,
    ) -> bytes:
        root = ElementTree.Element(
            "xfdf",
            xmlns="http://ns.adobe.com/xfdf/",
            xml_space="preserve",
        )
        ElementTree.SubElement(root, "f", href=original_name)
        annots = ElementTree.SubElement(root, "annots")
        for annotation in self.list_for_document(document_id, file_id=file_id):
            attributes = {
                "name": annotation.id,
                "page": str(annotation.page_number - 1),
                "color": annotation.color,
            }
            if annotation.quad_points:
                attributes["coords"] = ",".join(f"{value:.4f}" for value in annotation.quad_points)
            tag = "highlight" if annotation.annotation_type == "highlight" else "text"
            node = ElementTree.SubElement(annots, tag, attributes)
            if annotation.comment:
                contents = ElementTree.SubElement(node, "contents")
                contents.text = annotation.comment
        return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)

    def export_annotated_pdf(
        self,
        document_id: int,
        source: Path,
        destination: Path,
        *,
        file_id: int | None = None,
    ) -> Path:
        reader = PdfReader(source)
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        for annotation in self.list_for_document(document_id, file_id=file_id):
            page_index = annotation.page_number - 1
            if not 0 <= page_index < len(writer.pages):
                continue
            if annotation.annotation_type == "highlight" and len(annotation.quad_points) >= 8:
                xs = annotation.quad_points[0::2]
                ys = annotation.quad_points[1::2]
                rect = (min(xs), min(ys), max(xs), max(ys))
                highlight = Highlight(
                    rect=rect,
                    quad_points=ArrayObject(
                        [FloatObject(value) for value in annotation.quad_points]
                    ),
                    highlight_color=annotation.color.lstrip("#"),
                )
                highlight[NameObject("/Contents")] = TextStringObject(
                    annotation.comment or annotation.selected_text
                )
                writer.add_annotation(page_number=page_index, annotation=highlight)
            else:
                rect = _comment_rect(annotation.quad_points)
                writer.add_annotation(
                    page_number=page_index,
                    annotation=Text(
                        rect=rect,
                        text=annotation.comment or annotation.selected_text or "Bookmark",
                        open=False,
                    ),
                )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("wb") as handle:
            writer.write(handle)
        temporary.replace(destination)
        return destination

    @staticmethod
    def _contract(row: sqlite3.Row) -> Annotation:
        return Annotation(
            id=row["id"],
            article_id=int(row["document_id"]),
            asset_id=int(row["file_id"]),
            page_number=int(row["page_number"]),
            annotation_type=row["annotation_type"],
            color=row["color"],
            quad_points=json.loads(row["quad_points_json"] or "[]"),
            selected_text=row["selected_text"],
            context_hash=row["context_hash"],
            comment=row["comment"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _comment_rect(points: list[float]) -> tuple[float, float, float, float]:
    if len(points) >= 2:
        return (points[0], points[1], points[0] + 24, points[1] + 24)
    return (24, 24, 48, 48)
