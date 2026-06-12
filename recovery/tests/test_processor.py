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


def test_yoshida_filename_strips_whitespace_before_formatting() -> None:
    # Metadata values with leading/trailing spaces must produce the same
    # normalized filename as trimmed values (ISS-007: preview vs. actual match).
    result_with_spaces = PdfProcessor.build_yoshida_filename(
        {"box_no": " 1", "binder_no": "2 ", "seq": " 3 "}
    )
    result_clean = PdfProcessor.build_yoshida_filename(
        {"box_no": "1", "binder_no": "2", "seq": "3"}
    )

    assert result_with_spaces.ok
    assert result_with_spaces.normalized_filename == result_clean.normalized_filename
    assert result_with_spaces.normalized_filename == "01_02_003.pdf"


def test_yoshida_filename_whitespace_only_value_is_treated_as_missing() -> None:
    result = PdfProcessor.build_yoshida_filename({"box_no": "  ", "binder_no": "2", "seq": "3"})

    assert not result.ok
    assert "missing_required:box_no" in result.errors


def test_ensure_unique_path_adds_counter(tmp_path: Path) -> None:
    first = tmp_path / "01_02_003.pdf"
    first.write_text("existing", encoding="utf-8")

    assert PdfProcessor.ensure_unique_path(first) == tmp_path / "01_02_003_2.pdf"


def test_page_preview_returns_jpeg_data_url(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    data_url = PdfProcessor.page_preview_data_url(source, 1)

    assert data_url.startswith("data:image/jpeg;base64,")


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


# ISS-019 SEC-3: Windows reserved device name tests


def test_sanitize_filename_prefixes_reserved_name_con() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("CON.pdf")

    assert sanitized == "_CON.pdf"
    assert "reserved_name_prefixed" in warnings


def test_sanitize_filename_prefixes_reserved_name_lowercase_con() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("con.pdf")

    assert sanitized == "_con.pdf"
    assert "reserved_name_prefixed" in warnings


def test_sanitize_filename_prefixes_reserved_name_com1() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("COM1.pdf")

    assert sanitized == "_COM1.pdf"
    assert "reserved_name_prefixed" in warnings


def test_sanitize_filename_prefixes_reserved_name_lpt9() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("LPT9.pdf")

    assert sanitized == "_LPT9.pdf"
    assert "reserved_name_prefixed" in warnings


def test_sanitize_filename_prefixes_reserved_name_nul_no_extension() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("NUL")

    assert sanitized == "_NUL"
    assert "reserved_name_prefixed" in warnings


def test_sanitize_filename_does_not_affect_normal_name() -> None:
    sanitized, warnings = PdfProcessor.sanitize_filename("01_02_003.pdf")

    assert sanitized == "01_02_003.pdf"
    assert "reserved_name_prefixed" not in warnings


def test_sanitize_filename_does_not_affect_name_containing_reserved_word() -> None:
    # "CONSOLE.pdf" has stem "CONSOLE", which is not in the reserved list.
    sanitized, warnings = PdfProcessor.sanitize_filename("CONSOLE.pdf")

    assert sanitized == "CONSOLE.pdf"
    assert "reserved_name_prefixed" not in warnings
