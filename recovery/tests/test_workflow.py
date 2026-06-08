from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.models import Segment
from pdf_splitter_tool.workflow import check_segment_outputs, error_messages, resequence_segments


def test_error_messages_use_yoshida_field_labels() -> None:
    assert error_messages(("missing_required:box_no",)) == ("箱Noを入力してください",)


def test_resequence_segments_updates_seq_values(tmp_path: Path) -> None:
    segments = [Segment(tmp_path / "source.pdf", 1, 1, {"seq": "9"}), Segment(tmp_path / "source.pdf", 2, 2, {})]

    resequence_segments(segments, start=3, step=2)

    assert [segment.metadata["seq"] for segment in segments] == ["3", "5"]


def test_check_segment_outputs_reports_ready_and_invalid(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "seq": "4"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert checks[0].ok
    assert checks[0].filename == "01_02_003.pdf"
    assert not checks[1].ok
    assert checks[1].messages == ("バインダーNoを入力してください",)


def test_check_segment_outputs_simulates_duplicate_names(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "binder_no": "2", "seq": "3"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert [check.filename for check in checks] == ["01_02_003.pdf", "01_02_003_2.pdf"]


def test_check_segment_outputs_detects_existing_and_defaults_to_unique(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    existing = tmp_path / "01_02_003.pdf"
    existing.write_text("existing", encoding="utf-8")
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert checks[0].ok
    assert checks[0].has_existing_output
    assert checks[0].existing_path == existing
    assert checks[0].filename == "01_02_003_2.pdf"
    assert checks[0].output_path == tmp_path / "01_02_003_2.pdf"


def test_check_segment_outputs_keeps_requested_name_when_existing_and_batch_collide(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    (tmp_path / "01_02_003.pdf").write_text("existing", encoding="utf-8")
    (tmp_path / "01_02_003_2.pdf").write_text("existing", encoding="utf-8")
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "binder_no": "2", "seq": "3"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert [check.ok for check in checks] == [True, True]
    assert [check.requested_filename for check in checks] == ["01_02_003.pdf", "01_02_003.pdf"]
    assert [check.requested_path for check in checks] == [tmp_path / "01_02_003.pdf", tmp_path / "01_02_003.pdf"]
    assert [check.filename for check in checks] == ["01_02_003_3.pdf", "01_02_003_4.pdf"]
    assert [check.output_path for check in checks] == [tmp_path / "01_02_003_3.pdf", tmp_path / "01_02_003_4.pdf"]
    assert [check.existing_path for check in checks] == [tmp_path / "01_02_003.pdf", tmp_path / "01_02_003.pdf"]
    assert [check.has_existing_output for check in checks] == [True, True]


def test_check_segment_outputs_detects_invalid_page_range(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 3, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=2))

    assert not checks[0].ok
    assert checks[0].messages == ("分割範囲に存在しないページが含まれています: 1-3 (PDFは2ページ)",)


class PageCountProcessor:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    @staticmethod
    def build_yoshida_filename(metadata: dict[str, str], affix_defs: object = ()):
        from pdf_splitter_tool.processor import PdfProcessor

        return PdfProcessor.build_yoshida_filename(metadata, affix_defs)

    def page_count(self, _pdf_path: Path) -> int:
        return self._page_count
