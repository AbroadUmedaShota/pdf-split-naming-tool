from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.domain import build_yoshida_filename_preview
from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.processor import PdfProcessor
from pdf_splitter_tool.workflow import check_segment_outputs


def test_preview_and_preflight_use_same_normal_output_name(tmp_path: Path) -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}
    preview = build_yoshida_filename_preview(metadata)
    segment = Segment(tmp_path / "source.pdf", 1, 1, metadata)

    [check] = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert preview.ok
    assert preview.raw_filename == "01_02_003.pdf"
    assert preview.normalized_filename == "01_02_003.pdf"
    assert check.requested_filename == preview.normalized_filename
    assert check.requested_path == tmp_path / preview.normalized_filename
    assert check.filename == "01_02_003.pdf"
    assert check.output_path == tmp_path / "01_02_003.pdf"


def test_preview_and_preflight_use_same_name_with_affixes(tmp_path: Path) -> None:
    affix_defs = (
        {"key": "company", "label": "会社名", "position": "prefix"},
        {"key": "doc", "label": "契約書名", "position": "suffix"},
    )
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3", "company": "A商事", "doc": "基本契約"}
    preview = build_yoshida_filename_preview(metadata, affix_defs)
    segment = Segment(tmp_path / "source.pdf", 1, 1, metadata)

    [check] = check_segment_outputs(
        [segment], tmp_path, processor=PageCountProcessor(page_count=1), affix_defs=affix_defs
    )

    assert preview.ok
    assert preview.normalized_filename == "A商事_01_02_003_基本契約.pdf"
    assert check.requested_filename == preview.normalized_filename
    assert check.filename == "A商事_01_02_003_基本契約.pdf"


def test_preview_and_preflight_use_same_name_with_seq_digits(tmp_path: Path) -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}
    preview = build_yoshida_filename_preview(metadata, (), 4)
    segment = Segment(tmp_path / "source.pdf", 1, 1, metadata)

    [check] = check_segment_outputs(
        [segment], tmp_path, processor=PageCountProcessor(page_count=1), seq_digits=4
    )

    assert preview.normalized_filename == "01_02_0003.pdf"
    assert check.requested_filename == preview.normalized_filename
    assert check.filename == "01_02_0003.pdf"


def test_preview_and_preflight_use_same_normalized_output_name_for_invalid_chars(tmp_path: Path) -> None:
    metadata = {"box_no": "1/2", "binder_no": "3:4", "seq": "5*6"}
    preview = build_yoshida_filename_preview(metadata)
    segment = Segment(tmp_path / "source.pdf", 1, 1, metadata)

    [check] = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert preview.ok
    assert preview.raw_filename == "1/2_3:4_5*6.pdf"
    assert preview.normalized_filename == "1_2_3_4_5_6.pdf"
    assert check.requested_filename == preview.normalized_filename
    assert check.requested_path == tmp_path / preview.normalized_filename
    assert check.filename == "1_2_3_4_5_6.pdf"
    assert check.output_path == tmp_path / "1_2_3_4_5_6.pdf"


def test_preflight_keeps_preview_requested_name_when_batch_duplicates_are_numbered(tmp_path: Path) -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}
    preview = build_yoshida_filename_preview(metadata)
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, metadata),
        Segment(source, 2, 2, metadata),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert preview.normalized_filename == "01_02_003.pdf"
    assert [check.requested_filename for check in checks] == [
        preview.normalized_filename,
        preview.normalized_filename,
    ]
    assert [check.requested_path for check in checks] == [
        tmp_path / preview.normalized_filename,
        tmp_path / preview.normalized_filename,
    ]
    assert [check.filename for check in checks] == ["01_02_003.pdf", "01_02_003_2.pdf"]
    assert [check.output_path for check in checks] == [
        tmp_path / "01_02_003.pdf",
        tmp_path / "01_02_003_2.pdf",
    ]


def test_preflight_keeps_preview_requested_name_when_existing_file_forces_numbering(tmp_path: Path) -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}
    preview = build_yoshida_filename_preview(metadata)
    source = tmp_path / "source.pdf"
    (tmp_path / preview.normalized_filename).write_text("existing", encoding="utf-8")
    segments = [
        Segment(source, 1, 1, metadata),
        Segment(source, 2, 2, metadata),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert preview.normalized_filename == "01_02_003.pdf"
    assert [check.requested_filename for check in checks] == [
        preview.normalized_filename,
        preview.normalized_filename,
    ]
    assert [check.requested_path for check in checks] == [
        tmp_path / preview.normalized_filename,
        tmp_path / preview.normalized_filename,
    ]
    assert [check.filename for check in checks] == ["01_02_003_2.pdf", "01_02_003_3.pdf"]
    assert [check.output_path for check in checks] == [
        tmp_path / "01_02_003_2.pdf",
        tmp_path / "01_02_003_3.pdf",
    ]
    assert [check.existing_path for check in checks] == [
        tmp_path / preview.normalized_filename,
        tmp_path / preview.normalized_filename,
    ]


def test_preflight_reserves_numbered_names_after_existing_outputs_without_changing_requested_preview_name(
    tmp_path: Path,
) -> None:
    metadata = {"box_no": "1", "binder_no": "2", "seq": "3"}
    preview = build_yoshida_filename_preview(metadata)
    source = tmp_path / "source.pdf"
    (tmp_path / "01_02_003.pdf").write_text("existing", encoding="utf-8")
    (tmp_path / "01_02_003_2.pdf").write_text("existing numbered", encoding="utf-8")
    segments = [
        Segment(source, 1, 1, metadata),
        Segment(source, 2, 2, metadata),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert preview.normalized_filename == "01_02_003.pdf"
    assert [check.requested_filename for check in checks] == [
        preview.normalized_filename,
        preview.normalized_filename,
    ]
    assert [check.requested_path for check in checks] == [
        tmp_path / preview.normalized_filename,
        tmp_path / preview.normalized_filename,
    ]
    assert [check.filename for check in checks] == ["01_02_003_3.pdf", "01_02_003_4.pdf"]
    assert [check.output_path for check in checks] == [
        tmp_path / "01_02_003_3.pdf",
        tmp_path / "01_02_003_4.pdf",
    ]


class PageCountProcessor:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    @staticmethod
    def build_yoshida_filename(metadata: dict[str, str], affix_defs: object = (), seq_digits: object = 3):
        return PdfProcessor.build_yoshida_filename(metadata, affix_defs, seq_digits)

    def page_count(self, _pdf_path: Path) -> int:
        return self._page_count
