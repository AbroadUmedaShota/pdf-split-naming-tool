from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.models import MetadataField, Preset, Segment
from pdf_splitter_tool.output_controller import build_output_preflight_view
from pdf_splitter_tool.presets import YOSHIDA_ELSIS_PRESET
from pdf_splitter_tool.workflow import apply_common_metadata, check_segment_outputs, error_messages, resequence_segments


def test_error_messages_use_field_labels() -> None:
    assert error_messages(YOSHIDA_ELSIS_PRESET, ("missing_required:box_no",)) == ("箱Noを入力してください",)


def test_apply_common_metadata_and_resequence_segments(tmp_path: Path) -> None:
    segments = [Segment(tmp_path / "source.pdf", 1, 1, {"seq": "9"}), Segment(tmp_path / "source.pdf", 2, 2, {})]

    apply_common_metadata(segments, {"box_no": "1", "binder_no": "2"})
    resequence_segments(segments, start=3, step=2)

    assert [segment.metadata["box_no"] for segment in segments] == ["1", "1"]
    assert [segment.metadata["binder_no"] for segment in segments] == ["2", "2"]
    assert [segment.metadata["seq"] for segment in segments] == ["3", "5"]


def test_check_segment_outputs_reports_ready_and_invalid(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "seq": "4"}),
    ]

    checks = check_segment_outputs(segments, YOSHIDA_ELSIS_PRESET, tmp_path)

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

    checks = check_segment_outputs(segments, YOSHIDA_ELSIS_PRESET, tmp_path)

    assert [check.filename for check in checks] == ["01_02_003.pdf", "01_02_003_2.pdf"]


def test_template_key_error_is_actionable(tmp_path: Path) -> None:
    preset = Preset(
        id="case",
        name="Case",
        fields=(MetadataField("seq", "連番", required=True),),
        naming_template="{unknown}.pdf",
    )
    checks = check_segment_outputs([Segment(tmp_path / "source.pdf", 1, 1, {"seq": "1"})], preset, tmp_path)

    assert checks[0].messages == ("命名テンプレートの項目 unknown が入力項目にありません",)


def test_output_preflight_view_reports_ready_and_invalid(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segments = [
        Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"}),
        Segment(source, 2, 2, {"box_no": "1", "seq": "4"}),
    ]
    checks = check_segment_outputs(segments, YOSHIDA_ELSIS_PRESET, tmp_path)

    view = build_output_preflight_view(checks, tmp_path)

    assert view.ready_count == 1
    assert view.invalid_count == 1
    assert not view.can_run
    assert view.status_text == "要修正があります"
    assert view.summary_text == f"出力予定: 1件 / 要修正: 1件 / 保存先: {tmp_path}"
    assert any("01_02_003.pdf" in line.text and line.tag == "ok" for line in view.lines)
    assert any("バインダーNoを入力してください" in line.text and line.tag == "error" for line in view.lines)
