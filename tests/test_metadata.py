from __future__ import annotations

from pathlib import Path

from research_memory.services.metadata import (
    ExtractedPage,
    ExtractedPdf,
    TextBlock,
    infer_metadata,
)


def _block(text: str, *, y0: float, y1: float, x0: float = 48, x1: float = 540) -> TextBlock:
    return TextBlock(text=text, x0=x0, y0=y0, x1=x1, y1=y1)


def _extracted(
    blocks: list[TextBlock],
    *,
    text: str,
    metadata: dict[str, str] | None = None,
) -> ExtractedPdf:
    page = ExtractedPage(
        page_number=1,
        width=612,
        height=792,
        text=text,
        blocks=blocks,
        extraction_method="pdfium",
        confidence=1.0,
    )
    return ExtractedPdf(
        pages=[text],
        metadata=metadata or {},
        page_count=1,
        layout_pages=[page],
    )


def test_layout_metadata_ignores_contribution_statements_and_historical_years():
    title = "The role of bronchoscopy in the diagnosis of airway disease"
    extracted = _extracted(
        [
            _block("Review Article", y0=718, y1=725),
            _block(title, y0=678, y1=692),
            _block(
                "Tyler J. Paradis1, Jennifer Dixon2, Brandon H. Tieu3",
                y0=647,
                y1=657,
            ),
            _block("Department of Anesthesiology", y0=623, y1=632),
            _block(
                "Contributions: (I) Conception and design: All authors; "
                "(II) Administrative support: All authors",
                y0=597,
                y1=606,
            ),
        ],
        text=(
            f"{title}\nTyler J. Paradis, Jennifer Dixon, Brandon H. Tieu\n"
            "The flexible bronchoscope was introduced in 1967.\n"
            "Journal of Thoracic Disease 2016;8(12):3826-3837"
        ),
    )

    value = infer_metadata(extracted, Path("The role of bronchoscopy.pdf"))

    assert value["title"] == title
    assert value["authors"] == "Tyler J. Paradis, Jennifer Dixon, Brandon H. Tieu"
    assert value["publication_year"] == 2016


def test_layout_extends_short_embedded_title_and_subject_supplies_issue_year():
    extracted = _extracted(
        [
            _block("Basic Bronchoscopy", y0=645, y1=666, x1=240),
            _block(
                "Technology, Techniques, and Professional Fees",
                y0=625,
                y1=641,
                x1=365,
            ),
            _block(
                "Neil Ninan, MD, FCCP; and Momen M. Wahidi, MD, FCCP",
                y0=600,
                y1=608,
                x1=450,
            ),
            _block(
                "In 1967, the flexible bronchoscope changed pulmonary medicine.",
                y0=290,
                y1=300,
            ),
        ],
        text=(
            "Basic Bronchoscopy\nTechnology, Techniques, and Professional Fees\n"
            "Neil Ninan, MD, FCCP; and Momen M. Wahidi, MD, FCCP\n"
            "In 1967, the flexible bronchoscope changed pulmonary medicine."
        ),
        metadata={
            "Title": "Basic Bronchoscopy",
            "Author": "Neil Ninan MD FCCP",
            "Subject": "CHEST, 155 (2019) 1067-1074. doi:10.1016/j.chest.2019.02.009",
        },
    )

    value = infer_metadata(extracted, Path("Basic Bronchoscopy.pdf"))

    assert value["title"] == "Basic Bronchoscopy: Technology, Techniques, and Professional Fees"
    assert value["authors"] == "Neil Ninan, MD, FCCP; and Momen M. Wahidi, MD, FCCP"
    assert value["publication_year"] == 2019
    assert value["journal"] == "CHEST"


def test_layout_author_inference_skips_affiliation_markers_between_author_rows():
    extracted = _extracted(
        [
            _block("Flexible Bronchoscopy", y0=659, y1=682, x1=330),
            _block(
                "Russell J. Miller, MD; Roberto F. Casal, MD; Donald R. Lazarus, MD",
                y0=632,
                y1=643,
                x1=355,
            ),
            _block("b", y0=626, y1=631, x0=112, x1=116),
            _block(
                "David E. Ost, MD; George A. Eapen, MD",
                y0=619,
                y1=630,
                x1=230,
            ),
            _block("KEYWORDS", y0=592, y1=599, x1=92),
        ],
        text=(
            "Flexible Bronchoscopy\n"
            "Russell J. Miller, MD; Roberto F. Casal, MD; Donald R. Lazarus, MD\n"
            "b\nDavid E. Ost, MD; George A. Eapen, MD\nKEYWORDS"
        ),
        metadata={"Title": "Flexible Bronchoscopy", "Author": "Russell J. Miller MD"},
    )

    value = infer_metadata(extracted, Path("Flexible Bronchoscopy.pdf"))

    assert "George A. Eapen" in value["authors"]
    assert "David E. Ost" in value["authors"]


def test_publisher_artifact_metadata_yields_to_visible_title_and_byline():
    main_title = "Understanding the Economic Impact of Introducing a New Procedure"
    subtitle = (
        "Calculating Downstream Revenue of Endobronchial Ultrasound "
        "With Transbronchial Needle Aspiration as a Model"
    )
    extracted = _extracted(
        [
            _block(
                "CHEST Topics in Practice Management",
                y0=699,
                y1=728,
                x0=117,
                x1=533,
            ),
            _block(
                "Understanding the Economic Impact",
                y0=652,
                y1=668,
                x0=122,
                x1=450,
            ),
            _block(
                "of Introducing a New Procedure",
                y0=632,
                y1=648,
                x0=122,
                x1=407,
            ),
            _block(
                "Calculating Downstream Revenue of",
                y0=606,
                y1=620,
                x0=121,
                x1=377,
            ),
            _block(
                "Endobronchial Ultrasound With Transbronchial",
                y0=591,
                y1=602,
                x0=122,
                x1=447,
            ),
            _block(
                "Needle Aspiration as a Model",
                y0=572,
                y1=585,
                x0=122,
                x1=327,
            ),
            _block(
                "Nicholas J. Pastis, MD, FCCP; Suzanne Simkovich, MPAcc;",
                y0=544,
                y1=555,
                x0=121,
                x1=380,
            ),
            _block(
                "and Gerard A. Silvestri, MD, FCCP",
                y0=534,
                y1=543,
                x0=121,
                x1=279,
            ),
            *[
                _block(
                    f"Summary sentence number {index} describing downstream revenue.",
                    y0=493 - index * 11,
                    y1=503 - index * 11,
                    x0=79,
                    x1=497,
                )
                for index in range(7)
            ],
        ],
        text=(
            f"{main_title}\n{subtitle}\n"
            "Nicholas J. Pastis, MD, FCCP; Suzanne Simkovich, MPAcc;\n"
            "and Gerard A. Silvestri, MD, FCCP\n"
            "The word abstract appears incidentally in the body, not as a heading.\n"
            "CHEST 2012; 141(2):506-512"
        ),
        metadata={
            "Title": "chest110254.indd",
            "Author": "1087",
            "Subject": "CHEST 2012; 141(2):506-512",
        },
    )

    value = infer_metadata(extracted, Path(f"{main_title}.pdf"))

    assert value["title"] == f"{main_title}: {subtitle}"
    assert value["authors"] == (
        "Nicholas J. Pastis, MD, FCCP; Suzanne Simkovich, MPAcc; and Gerard A. Silvestri, MD, FCCP"
    )
    assert value["abstract"] == ""


def test_descriptive_filename_beats_a_body_fragment_when_no_title_geometry_exists():
    extracted = _extracted(
        [
            _block(
                "tumors that were bronchoscopically visualized and biopsied",
                y0=300,
                y1=310,
            )
        ],
        text="tumors that were bronchoscopically visualized and biopsied",
        metadata={"Title": "untitled"},
    )
    filename = Path(
        "Diagnostic Yield and Bleeding Complications Associated With "
        "Bronchoscopic Biopsy of Endobronchial Carcinoid Tumors.pdf"
    )

    value = infer_metadata(extracted, filename)

    assert value["title"] == filename.stem
