from pathlib import Path

import fitz
import pytest

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.processor import PdfProcessor


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def test_yoshida_filename_uses_fixed_required_fields() -> None:
    result = PdfProcessor.build_yoshida_filename({"box_no": "1", "binder_no": "2", "seq": "3"})

    assert result.ok
    assert result.normalized_filename == "01_02_003.pdf"


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"box_no": "9", "binder_no": "8", "seq": "7"}, "09_08_007.pdf"),
        ({"box_no": "12", "binder_no": "34", "seq": "56"}, "12_34_056.pdf"),
        ({"box_no": "123", "binder_no": "4", "seq": "5"}, "123_04_005.pdf"),
    ],
)
def test_yoshida_filename_zero_pads_box_binder_and_seq(metadata: dict[str, str], expected: str) -> None:
    result = PdfProcessor.build_yoshida_filename(metadata)

    assert result.ok
    assert result.raw_filename == expected
    assert result.normalized_filename == expected


def test_yoshida_filename_sanitizes_windows_invalid_filename_chars() -> None:
    result = PdfProcessor.build_yoshida_filename({"box_no": "1/2", "binder_no": '3:4', "seq": "5*6"})

    assert result.ok
    assert result.raw_filename == '1/2_3:4_5*6.pdf'
    assert result.normalized_filename == "1_2_3_4_5_6.pdf"
    assert result.warnings == ("filename_sanitized",)


def test_yoshida_filename_requires_box_binder_seq() -> None:
    result = PdfProcessor.build_yoshida_filename({"box_no": "1", "binder_no": "", "seq": "3"})

    assert not result.ok
    assert "missing_required:binder_no" in result.errors


def test_ensure_unique_path_adds_counter(tmp_path: Path) -> None:
    first = tmp_path / "01_02_003.pdf"
    first.write_text("existing", encoding="utf-8")

    assert PdfProcessor.ensure_unique_path(first) == tmp_path / "01_02_003_2.pdf"


def test_page_preview_returns_png_data_url(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    data_url = PdfProcessor.page_preview_data_url(source, 1)

    assert data_url.startswith("data:image/png;base64,")


def test_split_pdf_uses_one_based_inclusive_segment(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 5)
    segment = Segment(source, start_page=2, end_page=4)

    output = PdfProcessor.split_pdf(segment, tmp_path / "out.pdf")

    with fitz.open(output) as doc:
        assert doc.page_count == 3
        assert "Page 2" in doc.load_page(0).get_text()
        assert "Page 4" in doc.load_page(2).get_text()


def test_build_segments_by_n_pages(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"

    segments = PdfProcessor.build_segments_by_n_pages(source, page_count=5, pages_per_segment=2)

    assert [(segment.start_page, segment.end_page) for segment in segments] == [(1, 2), (3, 4), (5, 5)]
