"""Tests for research_assistant.docgen — PaperBuilder and BibTeX parsing."""

from pathlib import Path

import pytest
from docx import Document

from research_assistant.docgen import PaperBuilder, Reference, parse_bibtex


class TestReference:
    def test_format_apa_article(self):
        ref = Reference(
            key="smith2023",
            authors="Smith, J. and Doe, A.",
            title="A Great Paper",
            year=2023,
            journal="Nature",
            volume="42",
            pages="1-10",
            doi="10.1234/example",
        )
        text = ref.format_apa(1)
        assert text.startswith("[1]")
        assert "Smith, J. and Doe, A." in text
        assert '"A Great Paper."' in text
        assert "Nature," in text
        assert "vol. 42" in text
        assert "pp. 1-10" in text
        assert "2023." in text
        assert "DOI: 10.1234/example" in text

    def test_format_apa_inproceedings(self):
        ref = Reference(
            key="lee2022",
            authors="Lee, K.",
            title="Conference Paper",
            year=2022,
            booktitle="ICML 2022",
            pages="100-110",
        )
        text = ref.format_apa(3)
        assert "[3]" in text
        assert "in ICML 2022," in text

    def test_format_apa_minimal(self):
        ref = Reference(key="x", authors="A", title="T", year=2020)
        text = ref.format_apa(1)
        assert "[1]" in text
        assert "2020." in text


class TestPaperBuilder:
    def test_create_empty_doc(self, tmp_path):
        paper = PaperBuilder("Test Title")
        out = paper.save(str(tmp_path / "test.docx"))
        assert Path(out).exists()
        doc = Document(out)
        assert len(doc.paragraphs) > 0

    def test_title_and_authors(self, tmp_path):
        paper = PaperBuilder("My Paper", authors=["Alice", "Bob"])
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("My Paper" in t for t in texts)
        assert any("Alice, Bob" in t for t in texts)

    def test_abstract(self, tmp_path):
        paper = PaperBuilder("Title", abstract="This is the abstract text.")
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Abstract" in t for t in texts)
        assert any("abstract text" in t for t in texts)

    def test_affiliation(self, tmp_path):
        paper = PaperBuilder("Title", authors=["A"], affiliation="MIT")
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("MIT" in t for t in texts)

    def test_add_section(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_section("Introduction", "First paragraph.\n\nSecond paragraph.")
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Introduction" in t for t in texts)
        assert any("First paragraph." in t for t in texts)
        assert any("Second paragraph." in t for t in texts)

    def test_add_section_levels(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_section("Level 1", "Content", level=1)
        paper.add_section("Level 2", "Content", level=2)
        paper.add_section("Level 3", "Content", level=3)
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        headings = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert len(headings) == 3

    def test_add_section_level_clamped(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_section("Too High", "Content", level=5)
        paper.add_section("Too Low", "Content", level=0)
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        headings = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert len(headings) == 2

    def test_add_figure_missing_image(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_figure(str(tmp_path / "nonexistent.png"), "A caption")
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Missing figure" in t for t in texts)
        assert paper._figure_count == 0

    def test_add_figure_with_image(self, tmp_path):
        # Create a minimal valid PNG (1x1 pixel)
        import struct, zlib
        def _make_png():
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
            raw = b"\x00\x00\x00\x00"
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF
            idat = struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + struct.pack(">I", idat_crc)
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return sig + ihdr + idat + iend

        img = tmp_path / "fig1.png"
        img.write_bytes(_make_png())

        paper = PaperBuilder("Title")
        paper.add_figure(str(img), "Test caption")
        assert paper._figure_count == 1
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Figure 1. Test caption" in t for t in texts)

    def test_figure_auto_numbering(self, tmp_path):
        import struct, zlib
        def _make_png():
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
            raw = b"\x00\x00\x00\x00"
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF
            idat = struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + struct.pack(">I", idat_crc)
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return sig + ihdr + idat + iend

        img1 = tmp_path / "fig1.png"
        img2 = tmp_path / "fig2.png"
        img1.write_bytes(_make_png())
        img2.write_bytes(_make_png())

        paper = PaperBuilder("Title")
        paper.add_figure(str(img1), "First")
        paper.add_figure(str(img2), "Second")
        assert paper._figure_count == 2
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Figure 1." in t for t in texts)
        assert any("Figure 2." in t for t in texts)

    def test_add_table(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_table(["A", "B"], [["1", "2"], ["3", "4"]], caption="Results")
        assert paper._table_count == 1
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        assert len(doc.tables) == 1
        assert doc.tables[0].rows[0].cells[0].text == "A"
        texts = [p.text for p in doc.paragraphs]
        assert any("Table 1. Results" in t for t in texts)

    def test_table_auto_numbering(self, tmp_path):
        paper = PaperBuilder("Title")
        paper.add_table(["X"], [["1"]], caption="First")
        paper.add_table(["Y"], [["2"]], caption="Second")
        assert paper._table_count == 2
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("Table 1." in t for t in texts)
        assert any("Table 2." in t for t in texts)

    def test_add_references(self, tmp_path):
        refs = [
            Reference(key="a", authors="Smith", title="Paper A", year=2020, journal="J1"),
            Reference(key="b", authors="Jones", title="Paper B", year=2021, journal="J2"),
        ]
        paper = PaperBuilder("Title")
        paper.add_references(refs)
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("References" in t for t in texts)
        assert any("[1]" in t for t in texts)
        assert any("[2]" in t for t in texts)

    def test_save_creates_parents(self, tmp_path):
        paper = PaperBuilder("Title")
        out = paper.save(str(tmp_path / "a" / "b" / "paper.docx"))
        assert Path(out).exists()


class TestParseBibtex:
    def test_nonexistent_file(self):
        refs = parse_bibtex("/nonexistent/path.bib")
        assert refs == []

    def test_empty_file(self, tmp_path):
        bib = tmp_path / "empty.bib"
        bib.write_text("")
        refs = parse_bibtex(str(bib))
        assert refs == []

    def test_single_article(self, tmp_path):
        bib = tmp_path / "refs.bib"
        bib.write_text("""@article{smith2023,
  author = {Smith, John and Doe, Jane},
  title = {A Great Discovery},
  journal = {Nature},
  year = {2023},
  volume = {42},
  pages = {1-10},
  doi = {10.1234/example},
}
""")
        refs = parse_bibtex(str(bib))
        assert len(refs) == 1
        r = refs[0]
        assert r.key == "smith2023"
        assert r.authors == "Smith, John and Doe, Jane"
        assert r.title == "A Great Discovery"
        assert r.year == 2023
        assert r.journal == "Nature"
        assert r.volume == "42"
        assert r.pages == "1-10"
        assert r.doi == "10.1234/example"
        assert r.ref_type == "article"

    def test_multiple_entries(self, tmp_path):
        bib = tmp_path / "refs.bib"
        bib.write_text("""@article{a,
  author = {A},
  title = {Title A},
  year = {2020},
}

@inproceedings{b,
  author = {B},
  title = {Title B},
  year = {2021},
  booktitle = {ICML},
}
""")
        refs = parse_bibtex(str(bib))
        assert len(refs) == 2
        assert refs[0].ref_type == "article"
        assert refs[1].ref_type == "inproceedings"
        assert refs[1].booktitle == "ICML"

    def test_invalid_year(self, tmp_path):
        bib = tmp_path / "refs.bib"
        bib.write_text("""@article{x,
  author = {X},
  title = {Y},
  year = {unknown},
}
""")
        refs = parse_bibtex(str(bib))
        assert len(refs) == 1
        assert refs[0].year == 0

    def test_add_references_from_bibtex(self, tmp_path):
        bib = tmp_path / "refs.bib"
        bib.write_text("""@article{test,
  author = {Test Author},
  title = {Test Title},
  journal = {Test Journal},
  year = {2024},
}
""")
        paper = PaperBuilder("Title")
        paper.add_references_from_bibtex(str(bib))
        out = paper.save(str(tmp_path / "paper.docx"))
        doc = Document(out)
        texts = [p.text for p in doc.paragraphs]
        assert any("References" in t for t in texts)
        assert any("[1]" in t and "Test Author" in t for t in texts)
