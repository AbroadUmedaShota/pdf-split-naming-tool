from __future__ import annotations

from pathlib import Path

from pdf_splitter_tool.models import MetadataField, Preset, Segment
from pdf_splitter_tool.output_controller import build_output_preflight_view
from pdf_splitter_tool.presets import YOSHIDA_ELSIS_PRESET
from pdf_splitter_tool.step2_controller import (
    candidate_pages,
    current_page_state_text,
    page_badges,
    page_list_label,
    segment_for_page,
    segment_state_text,
    split_boundary_pages,
    visible_page_numbers,
)
from pdf_splitter_tool.workflow import (
    OUTPUT_ACTION_REUSE_EXISTING,
    OUTPUT_ACTION_SKIP,
    apply_common_metadata,
    check_segment_outputs,
    error_messages,
    metadata_suggestions_from_text,
    delete_segment_pages,
    extract_segment_pages,
    move_segment_page,
    output_action_key,
    resequence_segments,
    rotate_segment_pages,
    segment_page_plan,
)


def test_error_messages_use_field_labels() -> None:
    assert error_messages(YOSHIDA_ELSIS_PRESET, ("missing_required:box_no",)) == ("箱Noを入力してください",)


def test_apply_common_metadata_and_resequence_segments(tmp_path: Path) -> None:
    segments = [Segment(tmp_path / "source.pdf", 1, 1, {"seq": "9"}), Segment(tmp_path / "source.pdf", 2, 2, {})]

    apply_common_metadata(segments, {"box_no": "1", "binder_no": "2"})
    resequence_segments(segments, start=3, step=2)

    assert [segment.metadata["box_no"] for segment in segments] == ["1", "1"]
    assert [segment.metadata["binder_no"] for segment in segments] == ["2", "2"]
    assert [segment.metadata["seq"] for segment in segments] == ["3", "5"]


def test_page_organization_helpers_preserve_metadata_and_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 5, {"seq": "1"})

    deleted = delete_segment_pages(segment, {2, 4})
    rotated = rotate_segment_pages(deleted, {3}, 90)
    moved = move_segment_page(rotated, 5, -1)
    extracted = extract_segment_pages(moved, [5, 1])

    assert deleted.page_numbers == (1, 3, 5)
    assert rotated.rotations == {3: 90}
    assert moved.page_numbers == (1, 5, 3)
    assert extracted.page_numbers == (5, 1)
    assert extracted.rotations == {}
    assert extracted.metadata == {"seq": "1"}


def test_rotate_segment_pages_drops_noop_rotation(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"seq": "1"})

    rotated = segment
    for _ in range(4):
        rotated = rotate_segment_pages(rotated, {1}, 90)

    assert rotated.rotations == {}


def test_page_organization_helpers_drop_rotation_outside_page_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 5, {"seq": "1"}, page_numbers=(1, 3, 5), rotations={2: 90, 3: 180})

    moved = move_segment_page(segment, 5, -1)

    assert moved.page_numbers == (1, 5, 3)
    assert moved.rotations == {3: 180}


def test_segment_page_plan_keeps_order_and_rotation_for_history(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 5, {"seq": "1"}, page_numbers=(5, 1, 3), rotations={5: 90, 3: 180})

    assert segment_page_plan(segment) == {
        "source_pdf": str(source),
        "pages": "5,1,3",
        "page_numbers": [5, 1, 3],
        "rotations": {"5": 90, "3": 180},
    }


def test_metadata_suggestions_from_text_are_copy_friendly() -> None:
    text = "\n  株式会社A  \n\n契約書\n株式会社A\n箱No 01\nバインダー 02\n追加行\n"

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "株式会社A", "契約書"]


def test_metadata_suggestions_prioritize_labeled_values() -> None:
    text = """
    PDF OCR result
    箱No: 01
    バインダーNo：02
    連番 = 003
    会社名 株式会社A
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=5) == ["01", "02", "003", "株式会社A", "契約書"]


def test_metadata_suggestions_extract_generic_number_labels() -> None:
    text = """
    No. 01
    No 02
    番号 003
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "003", "契約書"]


def test_metadata_suggestions_extract_number_prefix_before_description() -> None:
    text = """
    No. 01 契約書
    No 02 Binder
    番号 003 控え
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["01", "02", "003"]


def test_metadata_suggestions_extract_values_without_label_separators() -> None:
    text = """
    箱No01
    バインダーNo02
    No.003
    会社名株式会社A
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "003", "株式会社A"]


def test_metadata_suggestions_extract_values_with_symbol_separators() -> None:
    text = """
    箱No-01
    バインダーNo/02
    No.-003
    Seq|004
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "003", "004"]


def test_metadata_suggestions_extract_values_from_no_dot_labels() -> None:
    text = """
    箱No. 01
    バインダーNo. 02
    BoxNo. 03
    BinderNo. 04
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "03", "04"]


def test_metadata_suggestions_extract_values_from_no_dot_labels_with_spaces() -> None:
    text = """
    箱 No . 01
    バインダー No . 02
    Box No . 03
    Binder No . 04
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "03", "04"]


def test_metadata_suggestions_extract_values_from_number_symbol_labels() -> None:
    text = """
    箱№01
    バインダー№ 02
    №003
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["01", "02", "003"]


def test_metadata_suggestions_extract_values_from_hash_number_labels() -> None:
    text = """
    箱#01
    バインダー # 02
    Box # 03
    No # 004
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "03", "004"]


def test_metadata_suggestions_extract_values_from_english_number_labels() -> None:
    text = """
    Box Number 01
    Binder Number 02
    Sequence Number 003
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["01", "02", "003"]


def test_metadata_suggestions_extract_values_from_seq_dot_labels() -> None:
    text = """
    Seq. 003
    Sequence. 004
    Seq.
    005
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["003", "004", "005"]


def test_metadata_suggestions_extract_values_from_spaced_japanese_number_labels() -> None:
    text = """
    箱 番号 01
    バインダー 番号 02
    """

    assert metadata_suggestions_from_text(text, limit=2) == ["01", "02"]


def test_metadata_suggestions_do_not_treat_notice_as_no_label() -> None:
    text = """
    Notice of contract
    No.003
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["003", "契約書", "Notice of contract"]


def test_metadata_suggestions_do_not_strip_short_japanese_words_as_labels() -> None:
    text = """
    箱入り書類
    バインダー保管資料
    箱01
    バインダー02
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "箱入り書類", "バインダー保管資料"]


def test_metadata_suggestions_normalize_fullwidth_label_values() -> None:
    text = """
    箱No０１
    ＢｉｎｄｅｒＮｏ０２
    Ｓｅｑ００３
    株式会社Ａ
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "003", "株式会社A"]


def test_metadata_suggestions_ignore_leading_bullets_before_labels() -> None:
    text = """
    - BoxNo01
    ・バインダーNo02
    ■Seq003
    * 会社名株式会社A
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "003", "株式会社A"]


def test_metadata_suggestions_do_not_strip_english_words_that_start_with_labels() -> None:
    text = """
    Documentary contract
    Companywide policy
    document 契約書
    company 株式会社A
    """

    assert metadata_suggestions_from_text(text, limit=4) == [
        "契約書",
        "株式会社A",
        "Documentary contract",
        "Companywide policy",
    ]


def test_metadata_suggestions_extract_values_from_english_name_labels() -> None:
    text = """
    Company Name Acme Inc
    Document Name Lease Agreement
    Contract Name Service Agreement
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["Acme Inc", "Lease Agreement", "Service Agreement"]


def test_metadata_suggestions_extract_values_from_spaced_japanese_name_labels() -> None:
    text = """
    会社 名 株式会社A
    書類 名 契約書
    契約書 名 賃貸借契約書
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["株式会社A", "契約書", "賃貸借契約書"]


def test_metadata_suggestions_use_value_after_standalone_label() -> None:
    text = """
    箱No
    01
    バインダー番号
    02
    会社名
    株式会社A
    書類名
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "株式会社A", "契約書"]


def test_metadata_suggestions_skip_empty_label_when_next_line_is_another_label() -> None:
    text = """
    会社名
    書類名
    契約書
    箱No
    バインダー番号
    02
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["契約書", "02"]


def test_metadata_suggestions_extract_labeled_value_after_standalone_label() -> None:
    text = """
    箱No
    No. 01
    バインダー番号
    番号 02
    連番
    Seq 003
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["01", "02", "003"]


def test_metadata_suggestions_extract_hash_value_after_number_label() -> None:
    text = """
    箱No
    # 01
    バインダー番号
    #02
    """

    assert metadata_suggestions_from_text(text, limit=2) == ["01", "02"]


def test_metadata_suggestions_extract_values_from_number_label_with_no_suffix() -> None:
    text = """
    連番No. 003
    連番番号 004
    seq No 005
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["003", "004", "005"]


def test_metadata_suggestions_respect_zero_limit() -> None:
    text = """
    箱No
    01
    会社名
    株式会社A
    """

    assert metadata_suggestions_from_text(text, limit=0) == []


def test_metadata_suggestions_use_value_after_standalone_label_with_separator() -> None:
    text = """
    箱No:
    01
    バインダー番号：
    02
    会社名 =
    株式会社A
    書類名 -
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=4) == ["01", "02", "株式会社A", "契約書"]


def test_metadata_suggestions_skip_separator_only_line_after_standalone_label() -> None:
    text = """
    箱No
    :
    01
    会社名
    =
    株式会社A
    書類名
    -
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=3) == ["01", "株式会社A", "契約書"]


def test_metadata_suggestions_use_value_after_empty_parenthesized_label() -> None:
    text = """
    会社名（）
    株式会社A
    書類名()
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=2) == ["株式会社A", "契約書"]


def test_metadata_suggestions_use_value_after_parenthesized_label_note() -> None:
    text = """
    会社名（契約者）
    株式会社A
    書類名(種類)
    契約書
    """

    assert metadata_suggestions_from_text(text, limit=2) == ["株式会社A", "契約書"]


def test_metadata_suggestions_extract_same_line_values_after_parenthesized_label_note() -> None:
    text = """
    会社名（契約者） 株式会社A
    書類名（種類）: 契約書
    """

    assert metadata_suggestions_from_text(text, limit=2) == ["株式会社A", "契約書"]


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


def test_check_segment_outputs_detects_existing_and_defaults_to_unique(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    existing = tmp_path / "01_02_003.pdf"
    existing.write_text("existing", encoding="utf-8")
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path)

    assert checks[0].ok
    assert checks[0].has_existing_output
    assert checks[0].existing_path == existing
    assert checks[0].filename == "01_02_003_2.pdf"
    assert checks[0].output_path == tmp_path / "01_02_003_2.pdf"


def test_check_segment_outputs_reuses_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    existing = tmp_path / "01_02_003.pdf"
    existing.write_text("existing", encoding="utf-8")
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})
    key = output_action_key(segment, "01_02_003.pdf")

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, output_actions={key: OUTPUT_ACTION_REUSE_EXISTING})

    assert checks[0].ok
    assert checks[0].action == OUTPUT_ACTION_REUSE_EXISTING
    assert checks[0].filename == "01_02_003.pdf"
    assert checks[0].output_path == existing


def test_check_segment_outputs_skip_is_runnable_without_output_path(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})
    key = output_action_key(segment, "01_02_003.pdf")

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, output_actions={key: OUTPUT_ACTION_SKIP})

    assert checks[0].ok
    assert checks[0].action == OUTPUT_ACTION_SKIP
    assert checks[0].filename == "01_02_003.pdf"
    assert checks[0].output_path is None


def test_check_segment_outputs_reuse_requires_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 1, {"box_no": "1", "binder_no": "2", "seq": "3"})
    key = output_action_key(segment, "01_02_003.pdf")

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, output_actions={key: OUTPUT_ACTION_REUSE_EXISTING})

    assert not checks[0].ok
    assert checks[0].messages == ("再利用対象の既存ファイルがありません",)


def test_check_segment_outputs_detects_invalid_page_plan_before_output(tmp_path: Path) -> None:
    class PageCountProcessor:
        @staticmethod
        def build_filename_templated(preset: Preset, metadata: dict[str, str]):
            from pdf_splitter_tool.processor import PdfProcessor

            return PdfProcessor.build_filename_templated(preset, metadata)

        @staticmethod
        def page_count(_pdf_path: Path) -> int:
            return 2

    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 3, {"box_no": "1", "binder_no": "2", "seq": "3"}, page_numbers=(1, 3))

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, processor=PageCountProcessor())

    assert not checks[0].ok
    assert checks[0].messages == ("ページ整理に存在しないページが含まれています: 3 (PDFは2ページ)",)


def test_check_segment_outputs_detects_duplicate_page_plan_before_output(tmp_path: Path) -> None:
    class PageCountProcessor:
        @staticmethod
        def build_filename_templated(preset: Preset, metadata: dict[str, str]):
            from pdf_splitter_tool.processor import PdfProcessor

            return PdfProcessor.build_filename_templated(preset, metadata)

        @staticmethod
        def page_count(_pdf_path: Path) -> int:
            return 3

    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 3, {"box_no": "1", "binder_no": "2", "seq": "3"}, page_numbers=(1, 2, 2, 3))

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, processor=PageCountProcessor())

    assert not checks[0].ok
    assert checks[0].messages == ("ページ整理に重複ページが含まれています: 2",)


def test_check_segment_outputs_detects_invalid_rotation_before_output(tmp_path: Path) -> None:
    class PageCountProcessor:
        @staticmethod
        def build_filename_templated(preset: Preset, metadata: dict[str, str]):
            from pdf_splitter_tool.processor import PdfProcessor

            return PdfProcessor.build_filename_templated(preset, metadata)

        @staticmethod
        def page_count(_pdf_path: Path) -> int:
            return 3

    source = tmp_path / "source.pdf"
    segment = Segment(source, 1, 3, {"box_no": "1", "binder_no": "2", "seq": "3"}, rotations={2: 45})

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, processor=PageCountProcessor())

    assert not checks[0].ok
    assert checks[0].messages == ("ページ整理に未対応の回転角度が含まれています: 2ページ=45度",)


def test_check_segment_outputs_detects_rotation_outside_page_plan_before_output(tmp_path: Path) -> None:
    class PageCountProcessor:
        @staticmethod
        def build_filename_templated(preset: Preset, metadata: dict[str, str]):
            from pdf_splitter_tool.processor import PdfProcessor

            return PdfProcessor.build_filename_templated(preset, metadata)

        @staticmethod
        def page_count(_pdf_path: Path) -> int:
            return 4

    source = tmp_path / "source.pdf"
    segment = Segment(
        source,
        1,
        4,
        {"box_no": "1", "binder_no": "2", "seq": "3"},
        page_numbers=(1, 3),
        rotations={4: 90},
    )

    checks = check_segment_outputs([segment], YOSHIDA_ELSIS_PRESET, tmp_path, processor=PageCountProcessor())

    assert not checks[0].ok
    assert checks[0].messages == ("ページ整理に対象外の回転指定が含まれています: 4ページ",)


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


def test_step2_page_state_helpers(tmp_path: Path) -> None:
    segments = [Segment(tmp_path / "source.pdf", 1, 2), Segment(tmp_path / "source.pdf", 3, 5)]
    boundaries = split_boundary_pages(segments, page_count=5)

    assert boundaries == {3}
    assert candidate_pages({1, 3}, {2}, {5}) == {1, 2, 3, 5}
    assert page_badges(3, {3}, {3}, set(), boundaries) == ["白紙", "検索", "分割前"]
    assert page_list_label(3, ["白紙", "検索", "分割前"]) == "   3ページ [白紙 検索 分割前]"
    assert visible_page_numbers(5, {2, 5}, candidates_only=True) == [2, 5]
    assert visible_page_numbers(3, set(), candidates_only=False) == [1, 2, 3]
    assert segment_for_page(segments, 4) == segments[1]
    assert segment_state_text(segments, 6, 8) == "未確定範囲: 6-8ページ"
    assert current_page_state_text(
        ["検索"],
        current_page=1,
        has_current_pdf=True,
        has_text_layer=False,
        has_search_query_hit=True,
        hit_count=2,
    ) == "検索 / OCR検索には事前OCR済みPDFが必要 / ページ内ヒット 2件 / 先頭ページのため前分割不可"
