from pdf_splitter_tool.app import (
    MAIN_TAB_LABELS,
    STEP2_DETAIL_TAB_LABELS,
    STEP3_SUGGESTION_COPY_HINT,
    TEXT_WIDGET_CLASSES,
    step3_suggestion_selected_status,
)


def test_text_widget_classes_block_global_shortcuts() -> None:
    assert "Entry" in TEXT_WIDGET_CLASSES
    assert "TEntry" in TEXT_WIDGET_CLASSES
    assert "Text" in TEXT_WIDGET_CLASSES
    assert "TCombobox" in TEXT_WIDGET_CLASSES


def test_step2_detail_tabs_are_named_for_smoke_verification() -> None:
    assert STEP2_DETAIL_TAB_LABELS == ("検出", "候補", "OCR本文", "操作")


def test_main_tabs_match_generic_pdf_organizer_flow() -> None:
    assert MAIN_TAB_LABELS == ("1 PDF取込", "2 ページ整理", "3 入力", "4 出力確認", "5 履歴")


def test_step3_suggestion_copy_hint_mentions_all_keyboard_paths() -> None:
    assert "Enter" in STEP3_SUGGESTION_COPY_HINT
    assert "Ctrl+C" in STEP3_SUGGESTION_COPY_HINT
    assert "ダブルクリック" in STEP3_SUGGESTION_COPY_HINT


def test_step3_suggestion_selected_status_is_shared_for_count_and_selection_only() -> None:
    assert step3_suggestion_selected_status("01", count=5) == (
        f"入力補助候補: 5件。選択中 01。{STEP3_SUGGESTION_COPY_HINT}"
    )
    assert step3_suggestion_selected_status("02") == f"入力補助候補: 選択中 02。{STEP3_SUGGESTION_COPY_HINT}"
