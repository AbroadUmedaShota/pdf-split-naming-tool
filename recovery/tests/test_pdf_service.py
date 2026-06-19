import base64
from pathlib import Path

import fitz
import pytest

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.pdf_service import MAX_PREVIEW_SIDE_PX, PdfService


def make_pdf(path: Path, pages: int, width: float = 595, height: float = 842) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def make_encrypted_pdf(path: Path, pages: int = 1, user_pw: str = "secret") -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_pw,
        owner_pw=user_pw,
    )
    doc.close()


def png_dimensions_from_data_url(data_url: str) -> tuple[int, int]:
    prefix = "data:image/jpeg;base64,"
    assert data_url.startswith(prefix)
    pixmap = fitz.Pixmap(base64.b64decode(data_url.removeprefix(prefix), validate=True))
    return pixmap.width, pixmap.height


def test_page_count_returns_document_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    assert PdfService.page_count(source) == 3


def test_page_preview_returns_png_data_url_for_one_based_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    data_url = PdfService.page_preview_data_url(source, 1)

    assert data_url.startswith("data:image/jpeg;base64,")
    width, height = png_dimensions_from_data_url(data_url)
    assert max(width, height) < MAX_PREVIEW_SIDE_PX
    assert width > 595
    assert height > 842


def test_page_preview_allows_exact_max_side_boundary(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1, width=2_000, height=2_000)

    data_url = PdfService.page_preview_data_url(source, 1)

    assert png_dimensions_from_data_url(data_url) == (MAX_PREVIEW_SIDE_PX, MAX_PREVIEW_SIDE_PX)


def test_page_preview_bounds_large_page_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1, width=10_000, height=4_000)

    data_url = PdfService.page_preview_data_url(source, 1)

    width, height = png_dimensions_from_data_url(data_url)
    assert max(width, height) <= MAX_PREVIEW_SIDE_PX
    assert width < 10_000 * 1.2
    assert height < 4_000 * 1.2


def test_page_preview_returns_final_page_from_one_based_page_number(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    data_url = PdfService.page_preview_data_url(source, 3)

    assert data_url.startswith("data:image/jpeg;base64,")


def test_page_preview_rejects_page_after_document_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 3)

    with pytest.raises(ValueError, match="page_no must be between"):
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

    with pytest.raises(ValueError, match="page_no must be between"):
        PdfService.page_preview_data_url(source, 0)


# ---------------------------------------------------------------------------
# Encrypted / password-protected PDF tests (issue #98)
# ---------------------------------------------------------------------------


def test_page_count_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.page_count(source)


def test_split_pdf_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source, pages=2)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.split_pdf(Segment(source, start_page=1, end_page=1), tmp_path / "out.pdf")


def test_split_pdf_encrypted_does_not_produce_output_file(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)
    out = tmp_path / "out.pdf"

    with pytest.raises(ValueError):
        PdfService.split_pdf(Segment(source, start_page=1, end_page=1), out)

    assert not out.exists(), "split_pdf must not create any output file for encrypted PDFs"


def test_page_text_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.page_text(source, 1)


def test_page_preview_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.page_preview_data_url(source, 1)


def test_search_text_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.search_text([source], "Page")


def test_search_highlights_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.search_highlights(source, 1, "Page")


def test_index_candidates_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.index_candidates([source])


def test_blank_candidates_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    make_encrypted_pdf(source)

    with pytest.raises(ValueError, match="パスワード付きPDF"):
        PdfService.blank_candidates(source)