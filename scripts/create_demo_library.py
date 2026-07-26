from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.embeddings import create_embedder
from research_memory.services.ingest import IngestionService

DEMO_PAPERS = [
    {
        "file": "robotic-bronchoscopy.pdf",
        "title": "Prospective Evaluation of Robotic Bronchoscopy for Peripheral Pulmonary Lesions",
        "author": "Amelia Chen; Marcus Rivera; Priya Shah",
        "pages": [
            """Prospective Evaluation of Robotic Bronchoscopy for Peripheral Pulmonary Lesions
Amelia Chen, Marcus Rivera, Priya Shah

Abstract
We conducted a prospective multicenter study among 218 patients with peripheral pulmonary lesions. The primary endpoint was strict diagnostic yield. Navigation success was 94.0%, while strict diagnostic yield was 72.5%. Benign diagnoses required 12 months of radiographic stability or an alternative definitive diagnosis. DOI: 10.5555/rb.2024.218

Introduction
Technical navigation and a clinically established diagnosis represent distinct outcomes.""",
            """Methods
Consecutive adults with lesions 8 to 30 mm were enrolled at six academic centers. Participants were not excluded for absence of a bronchus sign. Cone-beam computed tomography was used in 41% of procedures.

Results
Pneumothorax occurred in 3.2% and chest tube placement in 0.9%. Severe bleeding occurred in 1.4%.

Limitations
The study lacked a randomized comparator and most procedures were performed by experienced operators.""",
        ],
        "why": "The paper where navigation success was excellent but strict diagnostic yield was much lower; useful for teaching why technical success is not clinical success.",
    },
    {
        "file": "ebus-staging.pdf",
        "title": "False-Negative Nodal Staging After Systematic Endobronchial Ultrasound",
        "author": "Daniel Brooks; Sofia Almeida",
        "pages": [
            """False-Negative Nodal Staging After Systematic Endobronchial Ultrasound
Daniel Brooks and Sofia Almeida

Abstract
This retrospective cohort included 604 patients who underwent systematic endobronchial ultrasound staging followed by surgical nodal assessment. Missed nodal metastasis occurred in 5.5% of patients. DOI: 10.5555/ebus.2022.604

The primary outcome was occult N2 or N3 disease identified at surgery after a negative endobronchial ultrasound examination.""",
            """Results
False-negative examinations were more frequent when positron emission tomography showed fluorodeoxyglucose-avid nodes and when fewer than three mediastinal stations were sampled. The negative predictive value was 91.8%.

Limitations
The cohort was derived from two tertiary centers and surgical verification was not available for patients managed nonoperatively.""",
        ],
        "why": "Useful missed-nodal-metastasis rate and distinction between patient-level and station-level false negatives.",
    },
    {
        "file": "pleural-infection.pdf",
        "title": "Intrapleural Therapy for Complex Pleural Infection: A Randomized Trial",
        "author": "Helen Ward; Omar Hassan; Liam Taylor",
        "pages": [
            """Intrapleural Therapy for Complex Pleural Infection: A Randomized Trial
Helen Ward, Omar Hassan, Liam Taylor

Abstract
In this randomized controlled trial, 192 participants with pleural infection received combination intrapleural therapy or placebo. The primary outcome was the change in pleural opacity on chest radiography at day 7. DOI: 10.5555/pleura.2019.192

Combination therapy reduced referral for surgery and shortened hospital stay.""",
            """Results
Surgical referral occurred in 4.1% of the combination-therapy group and 15.8% of the placebo group. Median hospital stay was reduced by 6.7 days. Major bleeding was uncommon.

Limitations
The radiographic primary endpoint may not fully represent patient-centered recovery.""",
        ],
        "why": "Landmark trial with an imaging primary endpoint; important caveat that radiographic improvement is not itself patient-centered.",
    },
    {
        "file": "ecmo-anticoagulation.pdf",
        "title": "Anticoagulation Strategies During Venovenous Extracorporeal Membrane Oxygenation",
        "author": "Nora Evans; William Park",
        "pages": [
            """Anticoagulation Strategies During Venovenous Extracorporeal Membrane Oxygenation
Nora Evans and William Park

Abstract
This systematic review compared lower-intensity and conventional anticoagulation strategies during venovenous extracorporeal membrane oxygenation. Seventeen observational studies representing 2,431 patients were included. DOI: 10.5555/ecmo.2025.2431

Definitions of major bleeding and circuit thrombosis varied substantially across studies.""",
            """Results
Lower-intensity strategies were associated with fewer reported bleeding events, but confidence intervals were wide and residual confounding was likely. No consistent mortality difference was identified.

Limitations
All included comparisons were nonrandomized and outcome definitions were heterogeneous.""",
        ],
        "why": "Good example of why pooled estimates can be misleading when bleeding definitions differ across ECMO studies.",
    },
    {
        "file": "diagnostic-yield-definitions.pdf",
        "title": "Defining Diagnostic Yield in Peripheral Bronchoscopy Studies",
        "author": "Grace Kim; Ethan Patel; Ana Morales",
        "pages": [
            """Defining Diagnostic Yield in Peripheral Bronchoscopy Studies
Grace Kim, Ethan Patel, Ana Morales

Abstract
We reviewed 78 peripheral bronchoscopy studies and identified 12 distinct definitions of diagnostic yield. DOI: 10.5555/yield.2023.78

Some studies counted nonspecific benign pathology as diagnostic without follow-up, whereas others required treatment response, alternative definitive testing, or at least 12 months of radiographic stability.""",
            """Results
Applying a strict definition reduced the apparent pooled diagnostic yield from 81% to 69%. Studies differed in denominator handling, exclusion of lost follow-up, and treatment of atypical cells.

Conclusion
Outcome-definition heterogeneity can create differences in reported performance even when procedural results are similar.""",
        ],
        "why": "The review showing twelve different diagnostic-yield definitions and an approximately 12-point drop with strict adjudication.",
    },
]


def create_pdf(path: Path, title: str, author: str, pages: list[str]) -> None:
    document = canvas.Canvas(str(path), pagesize=letter)
    document.setTitle(title)
    document.setAuthor(author)
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    page_width, page_height = letter
    for text in pages:
        y = page_height - 54
        for paragraph in text.splitlines():
            if not paragraph.strip():
                y -= body.leading
                continue
            for line in simpleSplit(paragraph, body.fontName, body.fontSize, page_width - 108):
                document.drawString(54, y, line)
                y -= body.leading
        document.showPage()
    document.save()


async def build_demo(data_dir: Path, reset: bool) -> None:
    data_dir = data_dir.expanduser().resolve()
    marker = data_dir / ".research-memory-demo"
    if reset and data_dir.exists():
        if not marker.is_file():
            raise RuntimeError(
                f"Refusing to reset {data_dir}: the directory is not marked as demo data"
            )
        shutil.rmtree(data_dir)
    settings = Settings(data_dir=data_dir, chunk_chars=900, chunk_overlap=120)
    settings.ensure_directories()
    marker.write_text("Research Memory disposable demo library\n", encoding="utf-8")
    source_dir = data_dir / "demo-source-pdfs"
    source_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    db.initialize()
    embedder = create_embedder(
        settings.embedding_backend,
        settings.embedding_model,
        settings.resolved_model_dir,
    )
    ingestion = IngestionService(db, settings, embedder)

    db.execute(
        """
        INSERT INTO projects(name, description, project_type, central_question)
        SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM projects WHERE name = ?)
        """,
        (
            "Bronchoscopy outcome definitions",
            "A teaching and methods project comparing technical and clinical outcome definitions.",
            "curriculum",
            "How do outcome definitions change the apparent performance of diagnostic bronchoscopy?",
            "Bronchoscopy outcome definitions",
        ),
    )
    project = db.fetch_one(
        "SELECT id FROM projects WHERE name = ?", ("Bronchoscopy outcome definitions",)
    )
    project_id = int(project["id"])

    for item in DEMO_PAPERS:
        path = source_dir / item["file"]
        if not path.exists():
            create_pdf(path, item["title"], item["author"], item["pages"])
        result = await ingestion.ingest_path(path, copy_into_library=True)
        if result.document_id:
            db.execute(
                "UPDATE documents SET why_saved = ?, importance = ? WHERE id = ?",
                (item["why"], 4 if "bronch" in item["title"].lower() else 3, result.document_id),
            )
            if "Bronch" in item["title"] or "bronch" in item["title"]:
                db.execute(
                    """
                    INSERT OR IGNORE INTO project_documents(project_id, document_id, status)
                    VALUES (?, ?, 'included')
                    """,
                    (project_id, result.document_id),
                )
        print(f"{item['file']}: {result.status} — {result.message}")

    db.execute(
        """
        INSERT INTO watched_folders(folder_path, recursive, enabled, last_scanned_at)
        VALUES (?, 1, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(folder_path) DO UPDATE SET enabled = 1, last_scanned_at = CURRENT_TIMESTAMP
        """,
        (str(source_dir),),
    )
    print(f"\nDemo library ready at {data_dir}")
    print(f"Run: RESEARCH_MEMORY_DATA_DIR={data_dir} research-memory")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("./research_memory_data"))
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    asyncio.run(build_demo(args.data_dir.expanduser().resolve(), args.reset))


if __name__ == "__main__":
    main()
