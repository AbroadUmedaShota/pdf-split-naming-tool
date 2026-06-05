from pathlib import Path

import fitz
import pytest

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.pdf_service import PdfService


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def test_page_count_returns_document_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    assert PdfService.page_count(source) == 3


def test_page_preview_returns_png_data_url_for_one_based_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    data_url = PdfService.page_preview_data_url(source, 1)

    assert data_url.startswith("data:image/png;base64,")


def test_page_preview_returns_final_page_from_one_based_page_number(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    data_url = PdfService.page_preview_data_url(source, 3)

    assert data_url.startswith("data:image/png;base64,")


def test_page_preview_rejects_page_after_document_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    with pytest.raises(ValueError, match="exceeds document page count"):
        PdfService.page_preview_data_url(source, 4)


def test_split_pdf_single_page_uses_one_based_inclusive_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    output = PdfService.split_pdf(Segment(source, start_page=2, end_page=2), tmp_path / "out.pdf")

    with fitz.open(output) as doc:
        assert doc.page_count == 1
        assert "Page 2" in doc.load_page(0).get_text()


def test_split_pdf_range_uses_one_based_inclusive_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 5)

    output = PdfService.split_pdf(Segment(source, start_page=2, end_page=4), tmp_path / "out.pdf")

    with fitz.open(output) as doc:
        assert doc.page_count == 3
        assert "Page 2" in doc.load_page(0).get_text()
        assert "Page 4" in doc.load_page(2).get_text()


def test_split_pdf_full_range_uses_one_based_inclusive_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)

    output = PdfService.split_pdf(Segment(source, start_page=1, end_page=4), tmp_path / "out.pdf")

    with fitz.open(output) as doc:
        assert doc.page_count == 4
        assert "Page 1" in doc.load_page(0).get_text()
        assert "Page 4" in doc.load_page(3).get_text()


def test_split_pdf_rejects_range_beyond_document_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    with pytest.raises(ValueError, match="exceeds document page count"):
        PdfService.split_pdf(Segment(source, start_page=2, end_page=3), tmp_path / "out.pdf")


def test_split_pdf_rejects_zero_start_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    with pytest.raises(ValueError, match="1-based"):
        PdfService.split_pdf(Segment(source, start_page=0, end_page=1), tmp_path / "out.pdf")


def test_split_pdf_rejects_end_page_before_start_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 2)

    with pytest.raises(ValueError, match="greater than or equal to start"):
        PdfService.split_pdf(Segment(source, start_page=2, end_page=1), tmp_path / "out.pdf")


def test_page_preview_rejects_zero_page_number(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    with pytest.raises(ValueError, match="1-based"):
        PdfService.page_preview_data_url(source, 0)
