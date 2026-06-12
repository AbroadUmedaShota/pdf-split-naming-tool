from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.processor import PdfProcessor
from pdf_splitter_tool.workflow import check_segment_outputs, unique_output_path


def test_unique_output_path_avoids_reserved_names_in_same_preflight(tmp_path: Path) -> None:
    requested = tmp_path / "01_02_003.pdf"
    reserved = {requested, tmp_path / "01_02_003_2.pdf"}

    assert unique_output_path(requested, reserved) == tmp_path / "01_02_003_3.pdf"


def test_check_segment_outputs_reserves_duplicate_output_names_in_same_preflight(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 3, 3, {"box_no": "1", "binder_no": "2", "seq": "3"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=3))

    assert [check.ok for check in checks] == [True, True, True]
    assert [check.requested_filename for check in checks] == [
        "01_02_003.pdf",
        "01_02_003.pdf",
        "01_02_003.pdf",
    ]
    assert [check.filename for check in checks] == [
        "01_02_003.pdf",
        "01_02_003_2.pdf",
        "01_02_003_3.pdf",
    ]


def test_check_segment_outputs_blocks_when_existing_file_present(tmp_path: Path) -> None:
    # New behaviour: disk-level conflict => ok=False, no output path allocated.
    source = tmp_path / "source.pdf"
    existing = tmp_path / "01_02_003.pdf"
    existing.write_bytes(b"existing")
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    [check] = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert not check.ok
    assert check.has_existing_output
    assert check.existing_path == existing
    assert check.requested_path == existing
    assert check.output_path is None
    assert "output_exists" in check.messages
    assert check.filename == "01_02_003.pdf"


def test_check_segment_outputs_blocks_page_range_beyond_pdf_page_count(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 2, 4, {"box_no": "1", "binder_no": "2", "seq": "3"})

    [check] = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=3))

    assert not check.ok
    assert check.output_path is None
    assert check.messages == ("分割範囲に存在しないページが含まれています: 2-4 (PDFは3ページ)",)


def test_check_segment_outputs_reports_missing_required_metadata_with_japanese_label(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "seq": "3"})

    [check] = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert not check.ok
    assert check.messages == ("バインダーNoを入力してください",)


class PageCountProcessor:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    @staticmethod
    def build_yoshida_filename(metadata: dict[str, str], affix_defs: object = (), seq_digits: object = 3):
        return PdfProcessor.build_yoshida_filename(metadata, affix_defs, seq_digits)

    def page_count(self, _pdf_path: Path) -> int:
        return self._page_count
