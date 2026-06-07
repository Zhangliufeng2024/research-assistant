"""Document generation helpers for creating Word (.docx) documents.

Provides PaperBuilder — a high-level API for constructing scientific papers
with professional formatting, figure embedding, tables, and numbered references.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn


@dataclass
class Reference:
    """A single bibliographic reference."""
    key: str
    authors: str
    title: str
    year: int
    journal: str = ""
    volume: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    booktitle: str = ""
    publisher: str = ""
    ref_type: str = "article"

    def format_apa(self, number: int) -> str:
        """Format as a numbered reference string."""
        parts = [f"[{number}]"]
        if self.authors:
            parts.append(f"{self.authors}.")
        parts.append(f'"{self.title}."')
        if self.journal:
            parts.append(f"{self.journal},")
        elif self.booktitle:
            parts.append(f"in {self.booktitle},")
        if self.volume:
            vol = f"vol. {self.volume}"
            if self.pages:
                vol += f", pp. {self.pages}"
            parts.append(f"{vol},")
        elif self.pages:
            parts.append(f"pp. {self.pages},")
        parts.append(f"{self.year}.")
        if self.doi:
            parts.append(f"DOI: {self.doi}")
        return " ".join(parts)


def _set_cell_shading(cell, color: str) -> None:
    """Set background shading on a table cell."""
    shading = cell._element.get_or_add_tcPr()
    shd = shading.makeelement(qn("w:shd"), {
        qn("w:val"): "clear",
        qn("w:color"): "auto",
        qn("w:fill"): color,
    })
    shading.append(shd)


class PaperBuilder:
    """High-level builder for scientific Word documents.

    Usage::

        paper = PaperBuilder("My Title", authors=["Alice", "Bob"])
        paper.add_section("Introduction", "Body text here...")
        paper.add_figure("figures/fig1.png", "System overview.")
        paper.add_table(["A", "B"], [["1", "2"]], caption="Results")
        paper.add_references([Reference(key="smith2023", ...)])
        paper.save("final/manuscript.docx")
    """

    def __init__(
        self,
        title: str,
        authors: Optional[list[str]] = None,
        abstract: Optional[str] = None,
        affiliation: Optional[str] = None,
    ):
        self.doc = Document()
        self._figure_count = 0
        self._table_count = 0
        self._setup_styles()
        self._add_title_block(title, authors, affiliation)
        if abstract:
            self._add_abstract(abstract)

    def _setup_styles(self) -> None:
        """Configure page layout and text styles."""
        for section in self.doc.sections:
            section.page_width = Inches(8.5)
            section.page_height = Inches(11)
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        style = self.doc.styles["Normal"]
        style.font.size = Pt(11)
        style.font.name = "Times New Roman"
        style.paragraph_format.line_spacing = 1.15
        style.paragraph_format.space_after = Pt(6)

        for level in range(1, 4):
            name = f"Heading {level}"
            if name in self.doc.styles:
                h = self.doc.styles[name]
                h.font.name = "Times New Roman"
                h.font.color.rgb = RGBColor(0, 0, 0)
                if level == 1:
                    h.font.size = Pt(14)
                    h.font.bold = True
                elif level == 2:
                    h.font.size = Pt(12)
                    h.font.bold = True
                else:
                    h.font.size = Pt(11)
                    h.font.bold = True
                    h.font.italic = True

    def _add_title_block(
        self,
        title: str,
        authors: Optional[list[str]],
        affiliation: Optional[str],
    ) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(16)
        run.font.name = "Times New Roman"
        p.paragraph_format.space_after = Pt(4)

        if authors:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(", ".join(authors))
            run.font.size = Pt(12)
            run.font.name = "Times New Roman"
            p.paragraph_format.space_after = Pt(2)

        if affiliation:
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(affiliation)
            run.font.size = Pt(10)
            run.font.italic = True
            run.font.name = "Times New Roman"
            p.paragraph_format.space_after = Pt(12)

    def _add_abstract(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run("Abstract")
        run.bold = True
        run.font.size = Pt(11)
        run.font.name = "Times New Roman"
        p.paragraph_format.space_after = Pt(4)

        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = p.add_run(text)
        run.italic = True
        run.font.size = Pt(10)
        run.font.name = "Times New Roman"
        pf = p.paragraph_format
        pf.left_indent = Inches(0.5)
        pf.right_indent = Inches(0.5)
        pf.space_after = Pt(12)

    def add_section(self, title: str, content: str, level: int = 1) -> None:
        """Add a section with heading and body text.

        Args:
            title: Section heading text.
            content: Body text (plain text, may contain newlines for paragraphs).
            level: Heading level (1, 2, or 3).
        """
        level = max(1, min(3, level))
        self.doc.add_heading(title, level=level)

        for para_text in content.split("\n\n"):
            para_text = para_text.strip()
            if not para_text:
                continue
            p = self.doc.add_paragraph(para_text)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def add_figure(
        self,
        image_path: str,
        caption: str,
        label: Optional[str] = None,
        width_inches: float = 5.5,
    ) -> None:
        """Add a figure with auto-numbered caption.

        Args:
            image_path: Path to the image file.
            caption: Caption text.
            label: Optional label for cross-referencing.
            width_inches: Image width (default 5.5 for 1-inch margins on Letter).
        """
        path = Path(image_path)
        if not path.exists():
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(f"[Missing figure: {image_path}]")
            run.italic = True
            return

        self._figure_count += 1

        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        run = p.add_run()
        run.add_picture(str(path), width=Inches(width_inches))

        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cap.add_run(f"Figure {self._figure_count}. {caption}")
        run.italic = True
        run.font.size = Pt(10)
        run.font.name = "Times New Roman"
        cap.paragraph_format.space_after = Pt(12)

    def add_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        caption: Optional[str] = None,
    ) -> None:
        """Add a table with optional auto-numbered caption.

        Args:
            headers: Column header strings.
            rows: List of rows, each a list of cell strings.
            caption: Optional caption text.
        """
        self._table_count += 1

        if caption:
            cap = self.doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.paragraph_format.space_before = Pt(12)
            run = cap.add_run(f"Table {self._table_count}. {caption}")
            run.bold = True
            run.font.size = Pt(10)
            run.font.name = "Times New Roman"

        n_cols = len(headers)
        table = self.doc.add_table(rows=1, cols=n_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

        for i, header in enumerate(headers):
            cell = table.rows[0].cells[i]
            cell.text = header
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True
                    run.font.size = Pt(10)
                    run.font.name = "Times New Roman"
            _set_cell_shading(cell, "D9E2F3")

        for row_data in rows:
            row = table.add_row()
            for i, cell_text in enumerate(row_data):
                if i < n_cols:
                    cell = row.cells[i]
                    cell.text = str(cell_text)
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.size = Pt(10)
                            run.font.name = "Times New Roman"

        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)

    def add_references(self, references: list[Reference]) -> None:
        """Add a numbered References section.

        Args:
            references: List of Reference objects to format.
        """
        self.doc.add_heading("References", level=1)

        for i, ref in enumerate(references, 1):
            p = self.doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.4)
            p.paragraph_format.first_line_indent = Inches(-0.4)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(ref.format_apa(i))
            run.font.size = Pt(10)
            run.font.name = "Times New Roman"

    def add_references_from_bibtex(self, bib_path: str) -> None:
        """Parse a .bib file and add all entries as numbered references."""
        refs = parse_bibtex(bib_path)
        if refs:
            self.add_references(refs)

    def save(self, path: str) -> str:
        """Save the document. Creates parent directories if needed.

        Returns:
            Absolute path to the saved file.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(p))
        return str(p.resolve())


# ---------------------------------------------------------------------------
# BibTeX parser (simple regex-based, sufficient for machine-generated entries)
# ---------------------------------------------------------------------------

_ENTRY_RE = re.compile(
    r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.+?)\n\s*\}",
    re.DOTALL,
)

_FIELD_RE = re.compile(
    r"(\w+)\s*=\s*\{([^}]*)\}",
)


def parse_bibtex(bib_path: str) -> list[Reference]:
    """Parse a .bib file into a list of Reference objects."""
    path = Path(bib_path)
    if not path.exists():
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []

    refs: list[Reference] = []
    for match in _ENTRY_RE.finditer(text):
        ref_type = match.group(1).lower()
        key = match.group(2)
        body = match.group(3)

        fields: dict[str, str] = {}
        for fm in _FIELD_RE.finditer(body):
            fields[fm.group(1).lower()] = fm.group(2).strip()

        year_str = fields.get("year", "0")
        try:
            year = int(year_str)
        except ValueError:
            year = 0

        refs.append(Reference(
            key=key,
            authors=fields.get("author", ""),
            title=fields.get("title", ""),
            year=year,
            journal=fields.get("journal", ""),
            volume=fields.get("volume", ""),
            pages=fields.get("pages", ""),
            doi=fields.get("doi", ""),
            url=fields.get("url", ""),
            booktitle=fields.get("booktitle", ""),
            publisher=fields.get("publisher", ""),
            ref_type=ref_type,
        ))

    return refs
