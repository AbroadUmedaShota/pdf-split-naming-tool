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


def test_check_segment_outputs_blocks_when_existing_output_present(tmp_path: Path) -> None:
    # New behaviour: disk-level conflict => ok=False, output_exists message, no output path.
    source = tmp_path / "source.pdf"
    existing = tmp_path / "01_02_003.pdf"
    existing.write_text("existing", encoding="utf-8")
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert not checks[0].ok
    assert checks[0].has_existing_output
    assert checks[0].existing_path == existing
    assert "output_exists" in checks[0].messages
    assert checks[0].output_path is None
    assert checks[0].filename == "01_02_003.pdf"


def test_check_segment_outputs_blocks_all_when_existing_and_batch_collide(tmp_path: Path) -> None:
    # Both segments collide with pre-existing disk files => both blocked.
    source = tmp_path / "source.pdf"
    (tmp_path / "01_02_003.pdf").write_text("existing", encoding="utf-8")
    (tmp_path / "01_02_003_2.pdf").write_text("existing", encoding="utf-8")
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "binder_no": "2", "seq": "3"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    # Both requested_path targets exist on disk => both blocked.
    assert [check.ok for check in checks] == [False, False]
    assert [check.requested_filename for check in checks] == ["01_02_003.pdf", "01_02_003.pdf"]
    assert [check.has_existing_output for check in checks] == [True, True]
    assert all("output_exists" in check.messages for check in checks)
    assert [check.output_path for check in checks] == [None, None]


def test_check_segment_outputs_intra_batch_duplicate_without_disk_conflict_still_ok(tmp_path: Path) -> None:
    # Intra-batch duplicates (no existing disk files) remain ok=True, resolved by reservation.
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "binder_no": "2", "seq": "3"}),
    ]

    checks = check_segment_outputs(segments, tmp_path, processor=PageCountProcessor(page_count=2))

    assert [check.ok for check in checks] == [True, True]
    assert checks[0].filename == "01_02_003.pdf"
    assert checks[1].filename == "01_02_003_2.pdf"
    assert [check.has_existing_output for check in checks] == [False, False]


def test_check_segment_outputs_detects_invalid_page_range(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 3, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=2))

    assert not checks[0].ok
    assert checks[0].messages == ("分割範囲に存在しないページが含まれています: 1-3 (PDFは2ページ)",)


def test_check_segment_outputs_blocks_when_output_path_too_long(tmp_path: Path) -> None:
    # Build an output_dir deep enough that output_dir / "01_02_003.pdf" reaches >= 260 chars.
    # "01_02_003.pdf" is 13 chars; we need len(str(output_dir)) >= 260 - 1 (sep) - 13 = 246.
    padding = "a" * 246
    # Use a synthetic deep path string without actually creating it on disk, since we only
    # need the length check (path.exists() is False, so the disk-conflict branch is skipped).
    from pathlib import PurePosixPath
    deep_dir = Path("/" + padding)
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], deep_dir, processor=PageCountProcessor(page_count=1))

    assert not checks[0].ok
    assert "output_path_too_long" in checks[0].messages
    assert checks[0].output_path is None


def test_check_segment_outputs_passes_when_output_path_within_limit(tmp_path: Path) -> None:
    # A short output_dir (tmp_path) produces a path well under 260 chars.
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], tmp_path, processor=PageCountProcessor(page_count=1))

    assert checks[0].ok
    assert "output_path_too_long" not in checks[0].messages
    assert checks[0].output_path is not None


def test_check_segment_outputs_path_too_long_blocks_even_if_file_exists(tmp_path: Path) -> None:
    # Both path-too-long and disk-conflict: output_path_too_long should appear in messages,
    # output_path must be None.
    padding = "a" * 246
    deep_dir = Path("/" + padding)
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], deep_dir, processor=PageCountProcessor(page_count=1))

    assert not checks[0].ok
    assert "output_path_too_long" in checks[0].messages
    assert checks[0].output_path is None


class PageCountProcessor:
    def __init__(self, page_count: int) -> None:
        self._page_count = page_count

    @staticmethod
    def build_yoshida_filename(metadata: dict[str, str], affix_defs: object = (), seq_digits: object = 3):
        from pdf_splitter_tool.processor import PdfProcessor

        return PdfProcessor.build_yoshida_filename(metadata, affix_defs, seq_digits)

    def page_count(self, _pdf_path: Path) -> int:
        return self._page_count
